## Implementation for activity logging in views.py

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.core.paginator import Paginator, EmptyPage
from rest_framework.exceptions import NotFound

from authentication.models import User

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

class SupportTicketViewSet(viewsets.ModelViewSet):
    queryset = SupportTicket.objects.all().order_by('-created_at')
    serializer_class = SupportTicketSerializer
    permission_classes = [permissions.IsAuthenticated]

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
        if user.is_staff:
            return self.queryset
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
        # Count tickets by status
        all_tickets = SupportTicket.objects.all()
        open_tickets = all_tickets.filter(status='open').count()
        in_progress_tickets = all_tickets.filter(status='in_progress').count()
        resolved_tickets = all_tickets.filter(status='resolved').count()
        urgent_tickets = all_tickets.filter(priority='urgent').count()
        
        # Calculate average resolution time for resolved tickets
        avg_resolution_time = 0
        resolved_with_times = all_tickets.filter(
            status='resolved', 
            updated_at__isnull=False, 
            created_at__isnull=False
        )
        
        if resolved_with_times.exists():
            # Calculate the average time in hours
            from django.db.models import F, ExpressionWrapper, fields
            from django.db.models.functions import Extract
            
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
            'totalTickets': all_tickets.count(),
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
    def admin_staff(self, request):
        """
        Return a list of admin staff members who can be assigned to tickets
        """
        # Get all admin users based on user_type or is_staff
        admin_users = User.objects.filter(
            models.Q(user_type='admin') | models.Q(is_staff=True),
            is_active=True  # Only return active users
        ).order_by('first_name', 'last_name')
        
        # Format the response
        staff_data = []
        for user in admin_users:
            staff_data.append({
                'id': str(user.id),  # Ensure ID is a string to match frontend expectations
                'name': user.get_full_name() or user.email,  # Use email as fallback since username is None
                'email': user.email,
                'username': user.email,  # Since username is None in your model, use email instead
                'is_active': user.is_active
            })
        
        return Response(staff_data)
        
    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
            """
            Assign a ticket to a staff member
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
                    staff_user = User.objects.get(id=staff_id, is_staff=True)
                    ticket.assigned_to = staff_user
                    new_assignee = staff_user.get_full_name() or staff_user.username
                except User.DoesNotExist:
                    return Response(
                        {"error": "Staff member not found or does not have admin privileges"},
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
            
            serializer = self.get_serializer(ticket)
            return Response(serializer.data)
class CommentViewSet(viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
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