from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Sum, Q, F, Case, When, IntegerField, DecimalField
from django.db.models.functions import TruncMonth, TruncWeek, TruncDay

from partner.models import PartnerProfile
from .models import Payout, PayoutSetting, Earnings
from datetime import datetime
from rest_framework import serializers

from .serializers import (
    PayoutSerializer, 
    PayoutCreateSerializer, 
    PayoutUpdateSerializer, 
    PayoutSettingSerializer, 
    EarningsSerializer, 
    EarningsCreateSerializer, 
    EarningsUpdateSerializer,

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
    filterset_fields = ['status', 'payment_method']
    search_fields = ['id', 'partner__name', 'note', 'client_notes']
    ordering_fields = ['request_date', 'processed_date', 'amount']

    def get_serializer_class(self):
        if self.action == 'create':
            return PayoutCreateSerializer
        elif self.action in ['update', 'partial_update'] or self.action in ['process', 'complete', 'fail', 'cancel']:
            return PayoutUpdateSerializer
        return PayoutSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # For non-staff users, only show their own payouts
        if not self.request.user.is_staff:
            queryset = queryset.filter(partner__user=self.request.user)

        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')

        if start_date:
            try:
                start_date = datetime.fromisoformat(start_date)
                queryset = queryset.filter(request_date__gte=start_date)
            except ValueError:
                pass

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

    def perform_create(self, serializer):
        """Automatically associate the payout with the authenticated partner"""
        # For non-staff users, automatically use their partner profile
        if not self.request.user.is_staff:
            if not hasattr(self.request.user, 'partner_profile'):
                raise serializers.ValidationError(
                    {'partner': 'User does not have an associated partner profile'},
                    code=status.HTTP_400_BAD_REQUEST
                )
            # Add requested_by and partner to validated_data before calling save
            validated_data = serializer.validated_data
            validated_data['partner'] = self.request.user.partner_profile
            validated_data['requested_by'] = self.request.user
            serializer.save(**validated_data)
        else:
            # For staff users, they can specify the partner
            partner_id = serializer.validated_data.get('partner')
            if not partner_id:
                raise serializers.ValidationError(
                    {'partner': 'Partner ID is required for staff users'},
                    code=status.HTTP_400_BAD_REQUEST
                )
            
            # Ensure partner exists
            try:
                partner = PartnerProfile.objects.get(id=partner_id)
            except PartnerProfile.DoesNotExist:
                raise serializers.ValidationError(
                    {'partner': 'Partner does not exist'},
                    code=status.HTTP_400_BAD_REQUEST
                )
            
            validated_data = serializer.validated_data
            validated_data['requested_by'] = self.request.user
            serializer.save(**validated_data)

    @action(detail=False, methods=['patch'], url_path='update-my-settings')
    def update_my_settings(self, request):
        try:
            partner = request.user.partner_profile  # Ensure user is a partner
            payout_setting, _ = PayoutSetting.objects.get_or_create(partner=partner)

            data = request.data
            payment_method = data.get('payment_method')
            payment_details = data.get('payment_details', {})

            # Basic payment method validation
            if payment_method == 'paypal' and not payment_details.get('email'):
                return Response({"error": "Paypal email is required."}, status=status.HTTP_400_BAD_REQUEST)
            if payment_method == 'bank' and not all(key in payment_details for key in ['account_name', 'account_number', 'routing_number', 'bank_name']):
                return Response({"error": "All bank details are required."}, status=status.HTTP_400_BAD_REQUEST)
            if payment_method == 'mpesa' and not payment_details.get('phone_number'):
                return Response({"error": "Phone number is required for M-Pesa."}, status=status.HTTP_400_BAD_REQUEST)
            if payment_method == 'stripe' and not payment_details.get('account_id'):
                return Response({"error": "Stripe account ID is required."}, status=status.HTTP_400_BAD_REQUEST)

            # Update fields if provided
            payout_setting.payment_method = payment_method
            payout_setting.payment_details = payment_details
            payout_setting.minimum_payout_amount = data.get('minimum_payout_amount', payout_setting.minimum_payout_amount)
            payout_setting.auto_payout = data.get('auto_payout', payout_setting.auto_payout)
            payout_setting.payout_schedule = data.get('payout_schedule', payout_setting.payout_schedule)

            payout_setting.full_clean()  # Run model-level clean() validation
            payout_setting.save()

            serializer = PayoutSettingSerializer(payout_setting)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except AttributeError:
            return Response({"error": "No partner profile found."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


    @action(detail=True, methods=['get'])
    def timeline(self, request, pk=None):
        """Get status history for a payout"""
        payout = self.get_object()
        timeline = payout.status_changes.order_by('-timestamp')
        serializer = PayoutTimelineSerializer(timeline, many=True)
        return Response(serializer.data)

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
        serializer = PayoutSerializer(payout)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get summary statistics of payouts"""
        queryset = self.get_queryset()
        
        summary_data = {
            'total_payouts': queryset.count(),
            'pending_amount': queryset.filter(status=Payout.Status.PENDING).aggregate(total=Sum('amount'))['total'] or 0,
            'completed_amount': queryset.filter(status=Payout.Status.COMPLETED).aggregate(total=Sum('amount'))['total'] or 0,
            'processing_amount': queryset.filter(status=Payout.Status.PROCESSING).aggregate(total=Sum('amount'))['total'] or 0,
            'total_paid': queryset.filter(status=Payout.Status.COMPLETED).aggregate(total=Sum('amount'))['total'] or 0
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
    filterset_fields = ['payment_method', 'auto_payout', 'payout_schedule']

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # For non-staff users, only show their own settings
        if not self.request.user.is_staff:
            queryset = queryset.filter(partner__user=self.request.user)
        
        return queryset
        
    def perform_create(self, serializer):
        """Ensure the partner is valid before creating the setting"""
        if not self.request.user.is_staff and not hasattr(self.request.user, 'partner_profile'):
            raise serializers.ValidationError(
                {'partner': 'You must be a partner to create payout settings'},
                code=status.HTTP_400_BAD_REQUEST
            )
        
        # Auto-assign partner for non-staff users
        if not self.request.user.is_staff:
            serializer.save(partner=self.request.user.partner_profile)
        else:
            serializer.save()
    
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

    @action(detail=False, methods=['get'])
    def mine(self, request):
        """Get the current user's payout settings"""
        if not hasattr(request.user, 'partner_profile'):
            return Response({'detail': 'No partner profile found'}, status=status.HTTP_404_NOT_FOUND)
            
        try:
            instance = self.get_queryset().get(partner=request.user.partner_profile)
            serializer = self.get_serializer(instance)
            return Response(serializer.data)
        except PayoutSetting.DoesNotExist:
            return Response({'detail': 'No payout settings found'}, status=status.HTTP_404_NOT_FOUND)

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

        # For non-staff users, only show their own earnings
        if not self.request.user.is_staff:
            queryset = queryset.filter(partner__user=self.request.user)

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
    def create(self, validated_data):
        partner = validated_data['partner']
        amount = validated_data['amount']
        
        # Get available earnings to include in this payout
        available_earnings = Earnings.objects.filter(
            partner=partner,
            status=Earnings.Status.AVAILABLE
        ).order_by('date')
        
        # Mark earnings as processing
        total_included = 0
        for earning in available_earnings:
            if total_included + earning.amount <= amount:
                earning.mark_as_processing()
                total_included += earning.amount
            else:
                break
                
        if total_included < amount:
            raise serializers.ValidationError(
                "Not enough available earnings to cover the requested amount"
            )
        
        # Create the payout
        payout = super().create(validated_data)
        payout.amount = total_included  # Use actual included amount
        payout.save()
        
        return payout


    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Admin approves pending earnings to make them available"""
        earning = self.get_object()
        if earning.status != Earnings.Status.PENDING:
            return Response({'error': 'Only pending earnings can be approved'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        earning.status = Earnings.Status.AVAILABLE
        earning.save()
        serializer = self.get_serializer(earning)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Admin rejects pending earnings"""
        earning = self.get_object()
        reason = request.data.get('reason', 'Rejected by admin')
        
        if earning.status != Earnings.Status.PENDING:
            return Response({'error': 'Only pending earnings can be rejected'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        earning.status = Earnings.Status.CANCELLED
        earning.notes = f"{earning.notes or ''}\nRejection reason: {reason}"
        earning.save()
        serializer = self.get_serializer(earning)
        return Response(serializer.data)

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
        """Get summary of earnings with proper status filtering"""
        queryset = self.get_queryset()
        
        summary_data = {
            'total_earnings': queryset.aggregate(total=Sum('amount'))['total'] or 0,
            'available_earnings': queryset.filter(
                status=Earnings.Status.AVAILABLE
            ).aggregate(total=Sum('amount'))['total'] or 0,
            'pending_earnings': queryset.filter(
                status=Earnings.Status.PENDING
            ).aggregate(total=Sum('amount'))['total'] or 0,
            'processing_earnings': queryset.filter(
                status=Earnings.Status.PROCESSING
            ).aggregate(total=Sum('amount'))['total'] or 0,
            'paid_earnings': queryset.filter(
                status=Earnings.Status.PAID
            ).aggregate(total=Sum('amount'))['total'] or 0,
            'cancelled_earnings': queryset.filter(
                status=Earnings.Status.CANCELLED
            ).aggregate(total=Sum('amount'))['total'] or 0,
        }
        
        return Response(summary_data)
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get monthly/weekly stats for earnings"""
        time_frame = request.query_params.get('time_frame', 'monthly')
        
        if time_frame == 'monthly':
            truncate_func = TruncMonth('date')
        elif time_frame == 'weekly':
            truncate_func = TruncWeek('date')
        else:  # default to daily
            truncate_func = TruncDay('date')
        
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