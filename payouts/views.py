# payouts/views.py
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Sum, Q, F, Case, When, IntegerField, DecimalField
from django.db.models.functions import TruncMonth, TruncWeek, TruncDay
from .models import Payout, PayoutSetting, Earnings
from datetime import datetime
from django.db import models
from .serializers import (
    PayoutSerializer, 
    PayoutCreateSerializer, 
    PayoutUpdateSerializer, 
    PayoutSettingSerializer, 
    EarningsSerializer, 
    EarningsCreateSerializer, 
    EarningsUpdateSerializer
)
from django.db.transaction import atomic
from .services import PaymentProcessor

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100

class PayoutViewSet(viewsets.ModelViewSet):
    queryset = Payout.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'payment_method', 'partner']
    search_fields = ['id', 'partner__name', 'note']
    ordering_fields = ['request_date', 'processed_date', 'amount']

    def get_serializer_class(self):
        if self.action == 'create':
            return PayoutCreateSerializer
        elif self.action in ['update', 'partial_update'] or self.action in ['process', 'complete', 'fail', 'cancel']:
            return PayoutUpdateSerializer
        return PayoutSerializer
    def get_queryset(self):
        queryset = super().get_queryset()

        # Filter by date range if provided
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')

        if start_date:
            try:
                start_date = datetime.fromisoformat(start_date)
                queryset = queryset.filter(request_date__gte=start_date)
            except ValueError:
                pass  # Ignore invalid date formats

        if end_date:
            try:
                end_date = datetime.fromisoformat(end_date)
                queryset = queryset.filter(request_date__lte=end_date)
            except ValueError:
                pass

        # Filter by amount range
        min_amount = self.request.query_params.get('min_amount')
        max_amount = self.request.query_params.get('max_amount')

        if min_amount:
            queryset = queryset.filter(amount__gte=float(min_amount))
        if max_amount:
            queryset = queryset.filter(amount__lte=float(max_amount))

        return queryset


    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        payout = self.get_object()
        if not payout.can_process:
            return Response({'error': 'Payout cannot be processed'}, status=status.HTTP_400_BAD_REQUEST)
        
        payout = PaymentProcessor.process_payment(payout)
        payout.processed_by = request.user
        payout.save()
        
        serializer = PayoutSerializer(payout)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        payout = self.get_object()
        transaction_id = request.data.get('transaction_id')
        
        if not payout.can_complete:
            return Response({'error': 'Payout cannot be completed'}, status=status.HTTP_400_BAD_REQUEST)
        
        payout = PaymentProcessor.complete_payment(payout, transaction_id)
        payout.processed_by = request.user
        payout.save()
        
        serializer = PayoutSerializer(payout)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def fail(self, request, pk=None):
        payout = self.get_object()
        error_message = request.data.get('error_message', 'Payment processing failed')
        
        if payout.status not in [Payout.Status.PENDING, Payout.Status.PROCESSING]:
            return Response({'error': 'Payout cannot be marked as failed'}, status=status.HTTP_400_BAD_REQUEST)
        
        payout = PaymentProcessor.fail_payment(payout, error_message)
        payout.processed_by = request.user
        payout.save()
        
        serializer = PayoutSerializer(payout)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        payout = self.get_object()
        reason = request.data.get('reason')
        
        if not payout.can_cancel:
            return Response({'error': 'Payout cannot be cancelled'}, status=status.HTTP_400_BAD_REQUEST)
        
        payout.cancel(reason, request.user)
        
        # Reset earnings status to available
        for payout_ref in payout.referrals.all():
            if hasattr(payout_ref.referral, 'earning'):
                earning = payout_ref.referral.earning
                earning.status = 'available'
                earning.payout = None
                earning.save()
        
        serializer = PayoutSerializer(payout)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get summary statistics of payouts"""
        total_payouts = self.get_queryset().count()
        pending_amount = self.get_queryset().filter(status=Payout.Status.PENDING).aggregate(total=Sum('amount'))['total'] or 0
        completed_amount = self.get_queryset().filter(status=Payout.Status.COMPLETED).aggregate(total=Sum('amount'))['total'] or 0
        processing_amount = self.get_queryset().filter(status=Payout.Status.PROCESSING).aggregate(total=Sum('amount'))['total'] or 0
        
        summary_data = {
            'total_payouts': total_payouts,
            'pending_amount': pending_amount,
            'completed_amount': completed_amount,
            'processing_amount': processing_amount,
            'total_paid': completed_amount
        }
        
        return Response(summary_data)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get monthly/weekly stats for payouts"""
        time_frame = request.query_params.get('time_frame', 'monthly')
        
        if time_frame == 'monthly':
            truncate_func = TruncMonth('request_date')
        elif time_frame == 'weekly':
            truncate_func = TruncWeek('request_date')
        else:  # default to daily
            truncate_func = TruncDay('request_date')
        
        stats = self.get_queryset().annotate(
            period=truncate_func
        ).values('period').annotate(
            total_count=Count('id'),
            total_amount=Sum('amount'),
            completed_count=Count(Case(When(status=Payout.Status.COMPLETED, then=1), output_field=IntegerField())),
            completed_amount=Sum(Case(
                When(status=Payout.Status.COMPLETED, then=F('amount')),
                default=0,
                output_field=DecimalField(max_digits=12, decimal_places=2)
            ))
        ).order_by('period')
        
        return Response(list(stats))


class PayoutSettingViewSet(viewsets.ModelViewSet):
    queryset = PayoutSetting.objects.all()
    serializer_class = PayoutSettingSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['partner', 'payment_method', 'auto_payout', 'payout_schedule']

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by partner id
        partner_id = self.request.query_params.get('partner_id')
        if partner_id:
            queryset = queryset.filter(partner_id=partner_id)
            
        return queryset
    
    @action(detail=False, methods=['get'])
    def schedules(self, request):
        """Get available payout schedules"""
        schedules = dict(PayoutSetting._meta.get_field('payout_schedule').choices)
        return Response(schedules)
    
    @action(detail=False, methods=['get'])
    def payment_methods(self, request):
        """Get available payment methods"""
        methods = dict(Payout.PaymentMethod.choices)
        return Response(methods)


class EarningsViewSet(viewsets.ModelViewSet):
    queryset = Earnings.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'source', 'partner']
    search_fields = ['partner__name', 'notes']
    ordering_fields = ['date', 'amount', 'created_at']
    
    def get_serializer_class(self):
        if self.action == 'create':
            return EarningsCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return EarningsUpdateSerializer
        return EarningsSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()

        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')

        if start_date:
            try:
                start_date = datetime.fromisoformat(start_date)
                queryset = queryset.filter(date__gte=start_date)
            except ValueError:
                pass

        if end_date:
            try:
                end_date = datetime.fromisoformat(end_date)
                queryset = queryset.filter(date__lte=end_date)
            except ValueError:
                pass

        # Filter by amount range
        min_amount = self.request.query_params.get('min_amount')
        max_amount = self.request.query_params.get('max_amount')

        if min_amount:
            queryset = queryset.filter(amount__gte=float(min_amount))
        if max_amount:
            queryset = queryset.filter(amount__lte=float(max_amount))

        # Filter by payout status
        payout_status = self.request.query_params.get('payout_status')
        if payout_status:
            if payout_status == 'paid':
                queryset = queryset.filter(payout__isnull=False, status='paid')
            elif payout_status == 'unpaid':
                queryset = queryset.filter(Q(payout__isnull=True) | ~Q(status='paid'))

        return queryset

    
    @atomic
    @action(detail=True, methods=['post'])
    def mark_available(self, request, pk=None):
        """Mark an earning as available for payout"""
        earning = self.get_object()
        
        if earning.status != Earnings.Status.PENDING:
            return Response({'error': 'Only pending earnings can be marked as available'}, status=status.HTTP_400_BAD_REQUEST)
        
        success = earning.mark_as_available()
        if success:
            serializer = self.get_serializer(earning)
            return Response(serializer.data)
        else:
            return Response({'error': 'Failed to update status'}, status=status.HTTP_400_BAD_REQUEST)
    
    @atomic
    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        """Mark an earning as paid"""
        earning = self.get_object()
        
        if earning.status != Earnings.Status.PROCESSING:
            return Response({'error': 'Only processing earnings can be marked as paid'}, status=status.HTTP_400_BAD_REQUEST)
        
        success = earning.mark_as_paid()
        if success:
            serializer = self.get_serializer(earning)
            return Response(serializer.data)
        else:
            return Response({'error': 'Failed to update status'}, status=status.HTTP_400_BAD_REQUEST)
    
    @atomic
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel an earning"""
        earning = self.get_object()
        reason = request.data.get('reason')
        
        if earning.status == Earnings.Status.PAID:
            return Response({'error': 'Paid earnings cannot be cancelled'}, status=status.HTTP_400_BAD_REQUEST)
        
        success = earning.cancel(reason)
        if success:
            serializer = self.get_serializer(earning)
            return Response(serializer.data)
        else:
            return Response({'error': 'Failed to cancel earning'}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get summary of earnings"""
        partner_id = request.query_params.get('partner_id')
        
        queryset = self.get_queryset()
        if partner_id:
            queryset = queryset.filter(partner_id=partner_id)
        
        total_earnings = queryset.aggregate(total=Sum('amount'))['total'] or 0
        available_earnings = queryset.filter(status=Earnings.Status.AVAILABLE).aggregate(total=Sum('amount'))['total'] or 0
        pending_earnings = queryset.filter(status=Earnings.Status.PENDING).aggregate(total=Sum('amount'))['total'] or 0
        processing_earnings = queryset.filter(status=Earnings.Status.PROCESSING).aggregate(total=Sum('amount'))['total'] or 0
        paid_earnings = queryset.filter(status=Earnings.Status.PAID).aggregate(total=Sum('amount'))['total'] or 0
        
        summary_data = {
            'total_earnings': total_earnings,
            'available_earnings': available_earnings,
            'pending_earnings': pending_earnings,
            'processing_earnings': processing_earnings,
            'paid_earnings': paid_earnings
        }
        
        return Response(summary_data)
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get monthly/weekly stats for earnings"""
        time_frame = request.query_params.get('time_frame', 'monthly')
        
        if time_frame == 'monthly':
            truncate_func = TruncMonth('date')  # Changed from 'request_date' to 'date'
        elif time_frame == 'weekly':
            truncate_func = TruncWeek('date')   # Changed from 'request_date' to 'date'
        else:  # default to daily
            truncate_func = TruncDay('date')    # Changed from 'request_date' to 'date'
        
        stats = self.get_queryset().annotate(
            period=truncate_func
        ).values('period').annotate(
            total_count=Count('id'),
            total_amount=Sum('amount'),
            paid_count=Count(Case(
                When(status=Earnings.Status.PAID, then=1), 
                output_field=IntegerField()
            )),
            paid_amount=Sum(Case(
                When(status=Earnings.Status.PAID, then=F('amount')),
                default=0,
                output_field=DecimalField(max_digits=12, decimal_places=2)
            ))
        ).order_by('period')
        
        return Response(list(stats))