from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncDay
from .models import Referral, ReferralTimeline
from django.utils import timezone
from datetime import timedelta

from .serializers import (
    ReferralSerializer, ReferralCreateSerializer, 
    ReferralUpdateStatusSerializer, ReferralListSerializer,
    ReferralTimelineSerializer
)

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100

class ReferralViewSet(viewsets.ModelViewSet):
    queryset = Referral.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'user', 'product', 'referral_code']
    search_fields = ['client_name', 'client_email', 'company', 'notes']
    ordering_fields = ['date_submitted', 'updated_at', 'potential_commission', 'actual_commission']

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        user = request.user

        # Get referral code from user's partner profile if it exists
        user_referral_code = getattr(getattr(user, 'partner_profile', None), 'referral_code', None)

        # Get referral code provided in the request
        raw_provided_referral_code = validated_data.get('referral_code')

        # Determine the final referral code, allowing it to be None
        final_referral_code = user_referral_code or raw_provided_referral_code or None

        # Create referral without requiring referral code
        referral = serializer.save(user=user, referral_code=final_referral_code)
        
        output_serializer = ReferralSerializer(referral)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)


    def get_serializer_class(self):
        if self.action == 'create':
            return ReferralCreateSerializer
        elif self.action == 'update_status':
            return ReferralUpdateStatusSerializer
        elif self.action == 'list':
            return ReferralListSerializer
        return ReferralSerializer
    
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        
              # Check if user is a support agent (in 'Support Agents' group)
        is_support_agent = user.groups.filter(name='Support Agents').exists()

        # Filter if: non-staff OR staff who are support agents
        if not user.is_staff or (user.is_staff and is_support_agent):
            queryset = queryset.filter(user=user)
            
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
            
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        # Check if user is a support agent (in 'Support Agents' group)
        is_support_agent = user.groups.filter(name='Support Agents').exists()

        # Filter if: non-staff OR staff who are support agents
        if not user.is_staff or (user.is_staff and is_support_agent):
            queryset = queryset.filter(user=user)
        # Apply search filter if provided
        search_term = self.request.query_params.get('search')
        if search_term:
            queryset = queryset.filter(
                Q(client_name__icontains=search_term) |
                Q(client_email__icontains=search_term) |
                Q(client_phone__icontains=search_term) |
                Q(company__icontains=search_term) |
                Q(notes__icontains=search_term)
            )
        
        # Apply status filter if provided
        status_filter = self.request.query_params.get('status')
        if status_filter and status_filter != 'all':
            queryset = queryset.filter(status=status_filter)
        
        # Apply product filter if provided
        product_filter = self.request.query_params.get('product')
        if product_filter and product_filter != 'all':
            queryset = queryset.filter(product_id=product_filter)
        
        # Apply date filter if provided
        date_filter = self.request.query_params.get('date')
        if date_filter and date_filter != 'all':
            today = timezone.now().date()
            if date_filter == 'today':
                queryset = queryset.filter(date_submitted__date=today)
            elif date_filter == 'thisWeek':
                start_of_week = today - timedelta(days=today.weekday())
                queryset = queryset.filter(date_submitted__date__gte=start_of_week)
            elif date_filter == 'thisMonth':
                queryset = queryset.filter(date_submitted__month=today.month, date_submitted__year=today.year)
            elif date_filter == 'last3Months':
                three_months_ago = today - timedelta(days=90)
                queryset = queryset.filter(date_submitted__date__gte=three_months_ago)

        # ✅ Move partner filter above the return
        partner_id = self.request.query_params.get('partner_id')
        if partner_id:
            queryset = queryset.filter(user__partner_profile__id=partner_id)

        # Optional: commission filters can stay here too
        min_commission = self.request.query_params.get('min_commission')
        max_commission = self.request.query_params.get('max_commission')

        if min_commission:
            queryset = queryset.filter(potential_commission__gte=float(min_commission))
        if max_commission:
            queryset = queryset.filter(potential_commission__lte=float(max_commission))

        return queryset.order_by('-date_submitted')
        

    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        referral = self.get_object()
        serializer = self.get_serializer(referral, data=request.data, partial=True)
        
        if serializer.is_valid():
            self.perform_update(serializer)
            return Response(ReferralSerializer(referral).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Return referral statistics"""
        queryset = self.filter_queryset(self.get_queryset())
        
        stats = {
            'total_referrals': queryset.count(),
            'by_status': queryset.values('status').annotate(
                count=Count('id'),
                total_potential=Sum('potential_commission'),
                total_actual=Sum('actual_commission')
            ),
            'by_product': queryset.values(
                'product__name'
            ).annotate(
                count=Count('id')
            ).filter(product__isnull=False),
            'conversion_rate': {
                'all': queryset.filter(status='converted').count() / queryset.count() * 100 
                if queryset.count() > 0 else 0
            },
            'timeline': queryset.annotate(
                date=TruncDay('date_submitted')
            ).values('date').annotate(
                count=Count('id')
            ).order_by('date')[:30]
        }
        
        return Response(stats)
    
    @action(detail=True, methods=['post'])
    def add_timeline_note(self, request, pk=None):
        referral = self.get_object()
        note = request.data.get('note')
        
        if not note:
            return Response({'error': 'Note is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Create a new timeline entry when a note is added
        timeline_entry = ReferralTimeline.objects.create(
            referral=referral,
            status=referral.status,
            note=note,
            created_by=request.user
        )
        
        # Serialize and return the newly created timeline entry
        serializer = ReferralTimelineSerializer(timeline_entry)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def get_timeline(self, request, pk=None):
        referral = self.get_object()
        # Fetch the timeline entries for this specific referral
        timeline_entries = ReferralTimeline.objects.filter(referral=referral).order_by('-timestamp')
        # Serialize and return the timeline entries
        serializer = ReferralTimelineSerializer(timeline_entries, many=True)
        return Response(serializer.data)
