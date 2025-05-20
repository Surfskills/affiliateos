from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.core.paginator import Paginator, EmptyPage
from rest_framework.exceptions import NotFound

from authentication.models import User
from rest_framework.views import APIView

from django.db import models

from .models import SupportTicket, Comment, SupportTicketAttachment, ActivityLog
from .serializers import (
    SupportTicketSerializer, 
    CreateSupportTicketSerializer,
    UpdateSupportTicketSerializer, 
    CommentSerializer,
    AttachmentSerializer,
    ActivityLogSerializer
)

from rest_framework import permissions

class IsAdminOrSupportAgent(permissions.BasePermission):
    """
    Custom permission to only allow admin and support agent users to assign tickets.
    """
    def has_permission(self, request, view):
        # Check if user is authenticated and is either admin or support agent
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.is_staff and 
            request.user.user_type in ['admin', 'support_agent']
        )

class IsSupportAgentAssignedToTicket(permissions.BasePermission):
    """
    Custom permission to allow support agents to access tickets assigned to them or created by them.
    """
    def has_object_permission(self, request, view, obj):
        user = request.user
        # Admin can access any ticket
        if user.is_staff and user.user_type == 'admin':
            return True
        # Support agent can access tickets assigned to them OR created by them
        elif user.is_staff and user.user_type == 'support_agent':
            return obj.assigned_to == user or obj.submitted_by == user
        # Regular users can access their own tickets
        return obj.submitted_by == user

class SupportTicketViewSet(viewsets.ModelViewSet):
    queryset = SupportTicket.objects.all().order_by('-created_at')
    serializer_class = SupportTicketSerializer
    permission_classes = [permissions.IsAuthenticated, IsSupportAgentAssignedToTicket]

    def get_serializer_class(self):
        if self.action == 'create':
            return CreateSupportTicketSerializer
        elif self.action in ['update', 'partial_update']:
            return UpdateSupportTicketSerializer
        return super().get_serializer_class()

    def perform_create(self, serializer):
        ticket = serializer.save(submitted_by=self.request.user)
        
        # Log ticket creation activity
        ActivityLog.objects.create(
            ticket=ticket,
            activity_type='created',
            description=f"Ticket '{ticket.subject}' has been created",
            performed_by=self.request.user,
            metadata={
                'ticket_id': ticket.id,
                'subject': ticket.subject,
                'issue_category': ticket.issue_category,
                'priority': ticket.priority
            }
        )

    def perform_update(self, serializer):
        old_instance = self.get_object()
        old_status = old_instance.status
        old_priority = old_instance.priority
        old_assigned_to = old_instance.assigned_to
        
        ticket = serializer.save()
        
        # Log status change
        if old_status != ticket.status:
            ActivityLog.objects.create(
                ticket=ticket,
                activity_type='status_change',
                description=f"Status changed from '{old_status}' to '{ticket.status}'",
                performed_by=self.request.user,
                metadata={
                    'old_status': old_status,
                    'new_status': ticket.status
                }
            )
        
        # Log priority change
        if old_priority != ticket.priority:
            ActivityLog.objects.create(
                ticket=ticket,
                activity_type='priority_change',
                description=f"Priority changed from '{old_priority}' to '{ticket.priority}'",
                performed_by=self.request.user,
                metadata={
                    'old_priority': old_priority,
                    'new_priority': ticket.priority
                }
            )
        
        # Log assignment change
        if old_assigned_to != ticket.assigned_to:
            new_assignee = ticket.assigned_to.get_full_name() if ticket.assigned_to else "No one"
            old_assignee = old_assigned_to.get_full_name() if old_assigned_to else "No one"
            
            ActivityLog.objects.create(
                ticket=ticket,
                activity_type='assignment',
                description=f"Ticket reassigned from {old_assignee} to {new_assignee}",
                performed_by=self.request.user,
                metadata={
                    'old_assigned_to': old_assigned_to.id if old_assigned_to else None,
                    'new_assigned_to': ticket.assigned_to.id if ticket.assigned_to else None
                }
            )


    def get_queryset(self):
        user = self.request.user
        # Admins can see all tickets
        if user.is_staff and user.user_type == 'admin':
            return self.queryset
        # Support agents can see tickets assigned to them OR created by them
        elif user.is_staff and user.user_type == 'support_agent':
            return self.queryset.filter(
                models.Q(assigned_to=user) | 
                models.Q(submitted_by=user)
            )
        # Regular users (partners) can see only their own tickets
        return self.queryset.filter(submitted_by=user)

    @action(detail=True, methods=['post'])
    def add_comment(self, request, pk=None):
        ticket = self.get_object()
        comment = Comment.objects.create(
            ticket=ticket,
            author=request.user,
            content=request.data.get('content')
        )
        
        # Log comment activity
        ActivityLog.objects.create(
            ticket=ticket,
            activity_type='comment',
            description=f"Comment added by {request.user.get_full_name() or request.user.email}",
            performed_by=request.user,
            metadata={
                'comment_id': comment.id,
                'content_preview': comment.content[:100] + ('...' if len(comment.content) > 100 else '')
            }
        )
        
        return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def upload_attachment(self, request, pk=None):
        ticket = self.get_object()
        attachment = SupportTicketAttachment.objects.create(
            ticket=ticket,
            file=request.FILES['file']
        )
        
        # Log file upload activity
        ActivityLog.objects.create(
            ticket=ticket,
            activity_type='file_upload',
            description=f"File '{request.FILES['file'].name}' uploaded",
            performed_by=request.user,
            metadata={
                'attachment_id': attachment.id,
                'filename': request.FILES['file'].name,
                'filesize': request.FILES['file'].size
            }
        )
        
        return Response(AttachmentSerializer(attachment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path='attachments/(?P<attachment_id>[^/.]+)')
    def delete_attachment(self, request, pk=None, attachment_id=None):
        """
        Delete an attachment from a support ticket
        """
        ticket = self.get_object()
        
        try:
            attachment = SupportTicketAttachment.objects.get(id=attachment_id, ticket=ticket)
        except SupportTicketAttachment.DoesNotExist:
            return Response(
                {"error": "Attachment not found or does not belong to this ticket"},
                status=status.HTTP_404_NOT_FOUND
            )
            
        # Store filename before deletion for activity log
        filename = attachment.file.name.split('/')[-1]
        
        # Delete the attachment
        attachment.delete()
        
        # Log file deletion activity
        ActivityLog.objects.create(
            ticket=ticket,
            activity_type='file_delete',
            description=f"File '{filename}' deleted",
            performed_by=request.user,
            metadata={
                'filename': filename,
                'attachment_id': attachment_id
            }
        )
        
        return Response(status=status.HTTP_204_NO_CONTENT)
        
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """
        Return statistics about support tickets
        """
        # Filter tickets based on user role
        user = request.user
        
        # Get the filtered queryset based on user role
        filtered_tickets = self.get_queryset()
        
        # Count tickets by status
        open_tickets = filtered_tickets.filter(status='open').count()
        in_progress_tickets = filtered_tickets.filter(status='in_progress').count()
        resolved_tickets = filtered_tickets.filter(status='resolved').count()
        urgent_tickets = filtered_tickets.filter(priority='urgent').count()
        
        # Calculate average resolution time for resolved tickets
        avg_resolution_time = 0
        resolved_with_times = filtered_tickets.filter(
            status='resolved',
            updated_at__isnull=False,
            created_at__isnull=False
        )
        
        if resolved_with_times.exists():
            # Calculate the average time in hours
            from django.db.models import F, ExpressionWrapper, fields
            
            resolved_with_times = resolved_with_times.annotate(
                resolution_time=ExpressionWrapper(
                    F('updated_at') - F('created_at'),
                    output_field=fields.DurationField()
                )
            )
            
            total_hours = 0
            for ticket in resolved_with_times:
                # Convert duration to hours
                total_hours += ticket.resolution_time.total_seconds() / 3600
            
            avg_resolution_time = round(total_hours / resolved_with_times.count(), 1)
        
        return Response({
            'totalTickets': filtered_tickets.count(),
            'openTickets': open_tickets,
            'inProgressTickets': in_progress_tickets,
            'resolvedTickets': resolved_tickets,
            'averageResolutionTime': avg_resolution_time,
            'urgentTickets': urgent_tickets
        })
    
    @action(detail=True, methods=['get'])
    def activities(self, request, pk=None):
        ticket = self.get_object()
        page = request.query_params.get('page', 1)
        limit = request.query_params.get('limit', 20)

        try:
            page = int(page)
            limit = int(limit)
        except ValueError:
            return Response(
                {"error": "page and limit must be integers"},
                status=status.HTTP_400_BAD_REQUEST
            )

        activities = ticket.activity_logs.all()
        paginator = Paginator(activities, limit)
        
        try:
            page_obj = paginator.page(page)
        except EmptyPage:
            raise NotFound("Invalid page")

        serializer = ActivityLogSerializer(page_obj.object_list, many=True)
        
        return Response({
            'activities': serializer.data,
            'pagination': {
                'totalCount': paginator.count,
                'totalPages': paginator.num_pages,
                'currentPage': page_obj.number,
                'nextPage': page_obj.next_page_number() if page_obj.has_next() else None,
                'prevPage': page_obj.previous_page_number() if page_obj.has_previous() else None,
            }
        })

    # Add a dedicated status update endpoint to easily track status changes
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        ticket = self.get_object()
        old_status = ticket.status
        new_status = request.data.get('status')
        
        if new_status not in dict(SupportTicket.STATUS_CHOICES).keys():
            return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)
            
        ticket.status = new_status
        ticket.save()
        
        # Log status change
        ActivityLog.objects.create(
            ticket=ticket,
            activity_type='status_change',
            description=f"Status changed from '{old_status}' to '{new_status}'",
            performed_by=request.user,
            metadata={
                'old_status': old_status,
                'new_status': new_status
            }
        )
        
        serializer = self.get_serializer(ticket)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def support_staff(self, request):
        """Get all eligible support staff (admins and support agents)"""
        support_staff = User.objects.filter(
            models.Q(user_type='admin') | models.Q(user_type='support_agent'),
            is_active=True,
            is_staff=True
        ).order_by('first_name', 'last_name')

        staff_data = []
        for user in support_staff:
            staff_data.append({
                'id': str(user.id),
                'name': user.get_full_name() or user.email,
                'email': user.email,
                'user_type': user.user_type,
                'isAdmin': user.is_staff,
                'isSupportAgent': user.user_type == 'support_agent'
            })
        
        return Response(staff_data)
        
    # Update the assign action to use the permission class and handle notifications
    @action(detail=True, methods=['post'], permission_classes=[IsAdminOrSupportAgent])
    def assign(self, request, pk=None):
        """
        Assign a ticket to a staff member (admin or support agent)
        """
        ticket = self.get_object()
        staff_id = request.data.get('staff_id')
        
        # Get the current assigned user before making changes
        old_assigned_to = ticket.assigned_to
        
        # If staff_id is empty string or None, unassign the ticket
        if not staff_id:
            ticket.assigned_to = None
            new_assignee = "No one"
        else:
            try:
                # Allow assigning to either admin or support agent
                staff_user = User.objects.filter(
                    id=staff_id, 
                    is_active=True,
                    is_staff=True,
                    user_type__in=['admin', 'support_agent']
                ).first()
                
                if not staff_user:
                    return Response(
                        {"error": "Staff member not found or does not have appropriate privileges"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                    
                ticket.assigned_to = staff_user
                new_assignee = staff_user.get_full_name() or staff_user.email
            except Exception as e:
                return Response(
                    {"error": f"Error assigning ticket: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Save the ticket
        ticket.save()
        
        # Log assignment change
        old_assignee = old_assigned_to.get_full_name() if old_assigned_to else "No one"
        
        ActivityLog.objects.create(
            ticket=ticket,
            activity_type='assignment',
            description=f"Ticket reassigned from {old_assignee} to {new_assignee}",
            performed_by=request.user,
            metadata={
                'old_assigned_to': str(old_assigned_to.id) if old_assigned_to else None,
                'new_assigned_to': str(ticket.assigned_to.id) if ticket.assigned_to else None
            }
        )
        
        # TODO: Send notification to the newly assigned support agent
        # This could be implemented with Django signals or a notification system
        
        serializer = self.get_serializer(ticket)
        return Response(serializer.data)

class CommentViewSet(viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        
        # Admins can see all comments
        if user.is_staff and user.user_type == 'admin':
            return self.queryset
        # Support agents can only see comments on tickets assigned to them
        elif user.is_staff and user.user_type == 'support_agent':
            return self.queryset.filter(
                models.Q(ticket__assigned_to=user) | 
                models.Q(ticket__assigned_to__isnull=True) |
                models.Q(author=user)
            )
        # Regular users can see comments on their own tickets
        return self.queryset.filter(ticket__submitted_by=user)

    def perform_create(self, serializer):
        ticket_id = self.request.data.get('ticket')
        
        # Check if user has permission to comment on this ticket
        user = self.request.user
        if user.is_staff and user.user_type == 'admin':
            # Admin can comment on any ticket
            pass
        elif user.is_staff and user.user_type == 'support_agent':
            # Support agent can only comment on assigned tickets or unassigned tickets
            ticket = SupportTicket.objects.get(id=ticket_id)
            if ticket.assigned_to != user and ticket.assigned_to is not None:
                raise permissions.PermissionDenied("You can only comment on tickets assigned to you or unassigned tickets.")
        else:
            # Regular users can only comment on their own tickets
            ticket = SupportTicket.objects.get(id=ticket_id)
            if ticket.submitted_by != user:
                raise permissions.PermissionDenied("You can only comment on your own tickets.")
                
        comment = serializer.save(author=self.request.user)
        
        # Log comment activity
        ActivityLog.objects.create(
            ticket=comment.ticket,
            activity_type='comment',
            description=f"Comment added by {self.request.user.get_full_name() or self.request.user.email}",
            performed_by=self.request.user,
            metadata={
                'comment_id': comment.id,
                'content_preview': comment.content[:100] + ('...' if len(comment.content) > 100 else '')
            }
        )