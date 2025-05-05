from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Sum, Q, F, Case, When, IntegerField, DecimalField
from django.db.models.functions import TruncMonth, TruncWeek, TruncDay
from django.utils import timezone

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
import logging

logger = logging.getLogger(__name__)
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
        """Mark a payout as completed and update all associated earnings"""
        payout = self.get_object()
        transaction_id = request.data.get('transaction_id')
        
        if not payout.can_complete:
            return Response({'error': 'Payout cannot be completed'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            payout = PaymentProcessor.complete_payment(payout, transaction_id, request.user)
            serializer = PayoutSerializer(payout)
            return Response(serializer.data)
        except Exception as e:
            return Response(
                {'error': f'Failed to complete payout: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
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
    # @action(detail=False, methods=['get'], url_path='monthly-earnings')
    # def monthly_earnings(self, request):
    #     payouts = Payout.objects.all()  # Or apply any necessary filters

    #     if not payouts.exists():
    #         return Response([], status=status.HTTP_200_OK)  # Return empty array if no payouts

    #     # Process and return the earnings data as you already have in your backend logic
    #     # For example:
    #     earnings = payouts.aggregate(
    #         total_count=Count('id'),
    #         total_amount=Sum('amount')
    #     )
    #     return Response(earnings)
    @action(detail=True, methods=['post'])
    def force_update_earnings(self, request, pk=None):
        """
        Debug action to force update all available earnings for this payout's partner
        This can help identify if there are any issues with the update logic
        """
        if not request.user.is_staff:
            return Response({'error': 'Staff only action'}, status=status.HTTP_403_FORBIDDEN)
        
        payout = self.get_object()
        from payouts.models import Earnings
        
        try:
            # Get all available earnings for this partner
            available_earnings = Earnings.objects.filter(
                partner=payout.partner,
                status=Earnings.Status.AVAILABLE
            )
            
            # Update them to paid status
            update_count = 0
            for earning in available_earnings:
                old_status = earning.status
                earning.status = Earnings.Status.PAID
                earning.payout = payout
                earning.paid_date = timezone.now()
                earning.save()
                update_count += 1
                logger.info(f"Force updated earning {earning.id} from {old_status} to {earning.status}")
            
            return Response({
                'success': True,
                'message': f'Force updated {update_count} earnings to paid status',
                'earnings_count': update_count
            })
        except Exception as e:
            logger.error(f"Error in force_update_earnings: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

import logging
from rest_framework.response import Response
from rest_framework import status, serializers
from rest_framework.decorators import action
from rest_framework import viewsets, permissions
from django_filters.rest_framework import DjangoFilterBackend

# Set up the logger
logger = logging.getLogger(__name__)

class PayoutSettingViewSet(viewsets.ModelViewSet):
    queryset = PayoutSetting.objects.all()
    serializer_class = PayoutSettingSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['payment_method', 'auto_payout', 'payout_schedule']

    def get_queryset(self):
        logger.debug("Fetching queryset.")
        queryset = super().get_queryset()
        
        # For non-staff users, only show their own settings
        if not self.request.user.is_staff:
            logger.debug(f"User is not staff. Filtering by partner {self.request.user.partner_profile}.")
            queryset = queryset.filter(partner__user=self.request.user)
        
        return queryset
        
    def create(self, request, *args, **kwargs):
        """Handle creation of payout settings with proper validation"""
        if not request.user.is_staff and not hasattr(request.user, 'partner_profile'):
            logger.error("User is not a partner and attempted to create payout settings.")
            return Response(
                {'partner': 'You must be a partner to create payout settings'},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = request.data.copy()
        
        # For non-staff users, auto-assign their partner profile
        if not request.user.is_staff:
            data['partner'] = request.user.partner_profile.id

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
    
    @action(detail=False, methods=['get'])
    def schedules(self, request):
        """Get available payout schedules"""
        logger.debug("Fetching payout schedules.")
        schedules = dict(PayoutSetting.PAYOUT_SCHEDULE_CHOICES)
        return Response({
            'choices': schedules,
            'default': PayoutSetting.DEFAULT_PAYOUT_SCHEDULE
        })
    
    @action(detail=False, methods=['get'])
    def payment_methods(self, request):
        """Get available payment methods"""
        logger.debug("Fetching payment methods.")
        methods = dict(Payout.PaymentMethod.choices)
        return Response({
            'choices': methods,
            'default': PayoutSetting.DEFAULT_PAYMENT_METHOD
        })

    @action(detail=False, methods=['get', 'patch', 'post'])
    def mine(self, request):
        """Get, update, or create the current user's payout settings"""
        if not hasattr(request.user, 'partner_profile'):
            return Response(
                {'detail': 'No partner profile found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
            
        try:
            instance = PayoutSetting.objects.get(partner=request.user.partner_profile)
        except PayoutSetting.DoesNotExist:
            instance = None
                
        if request.method == 'GET':
            if not instance:
                return Response({
                    'detail': 'No payout settings found',
                    'defaults': {
                        'payment_method': PayoutSetting.DEFAULT_PAYMENT_METHOD,
                        'payout_schedule': PayoutSetting.DEFAULT_PAYOUT_SCHEDULE,
                        'minimum_payout_amount': PayoutSetting.DEFAULT_MINIMUM_PAYOUT,
                        'auto_payout': False
                    }
                }, status=status.HTTP_200_OK)
            
            serializer = PayoutSettingSerializer(instance)
            return Response(serializer.data)

        elif request.method == 'POST':
            # Handle creation of new settings
            data = request.data.copy()
            
            # Remove payment_details if present (should be handled via add_payment_method)
            if 'payment_details' in data:
                del data['payment_details']
                
            # Ensure minimum_payout_amount is a float
            if 'minimum_payout_amount' in data:
                try:
                    data['minimum_payout_amount'] = float(data['minimum_payout_amount'])
                except ValueError:
                    return Response(
                        {'detail': 'Invalid format for minimum_payout_amount'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # Auto-assign partner
            data['partner'] = request.user.partner_profile.id
            
            serializer = PayoutSettingSerializer(data=data)
            if not serializer.is_valid():
                return Response(
                    serializer.errors,
                    status=status.HTTP_400_BAD_REQUEST
                )
                
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        elif request.method == 'PATCH':
            data = request.data.copy()
            
            # Remove payment_details if present (should be handled via add_payment_method)
            if 'payment_details' in data:
                del data['payment_details']
                
            # Ensure minimum_payout_amount is a float
            if 'minimum_payout_amount' in data:
                try:
                    data['minimum_payout_amount'] = float(data['minimum_payout_amount'])
                except ValueError:
                    return Response(
                        {'detail': 'Invalid format for minimum_payout_amount'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            if instance:
                # Update existing settings
                serializer = PayoutSettingSerializer(instance, data=data, partial=True)
            else:
                # Create new settings via PATCH (fallback)
                data['partner'] = request.user.partner_profile.id
                serializer = PayoutSettingSerializer(data=data)

            if not serializer.is_valid():
                return Response(
                    serializer.errors,
                    status=status.HTTP_400_BAD_REQUEST
                )

            serializer.save()

            if getattr(instance, '_prefetched_objects_cache', None):
                instance._prefetched_objects_cache = {}

            return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def add_payment_method(self, request):
        """
        Add or update a payment method for the current user's payout settings
        """
        logger.debug("Adding or updating payment method.")
        if not hasattr(request.user, 'partner_profile'):
            logger.warning(f"User {request.user} does not have a partner profile.")
            return Response(
                {'detail': 'No partner profile found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Validate required fields
        required_fields = ['payment_method', 'payment_details']
        for field in required_fields:
            if field not in request.data:
                logger.error(f"Missing required field: {field}")
                return Response(
                    {'detail': f'{field} is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        payment_method = request.data['payment_method']
        payment_details = request.data['payment_details']
        
        # Validate payment method
        valid_methods = dict(Payout.PaymentMethod.choices).keys()
        if payment_method not in valid_methods:
            logger.error(f"Invalid payment method: {payment_method}")
            return Response(
                {
                    'detail': f'Invalid payment method. Must be one of {", ".join(valid_methods)}',
                    'valid_methods': list(valid_methods)
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate payment details structure
        if not isinstance(payment_details, dict):
            logger.error("Payment details must be an object.")
            return Response(
                {'detail': 'payment_details must be an object'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Flatten details if nested under the method key
        formatted_details = self._format_payment_details(payment_method, payment_details)
        logger.debug(f"Formatted payment_details: {formatted_details}")

        # Method-specific validation
        validation_errors = {}

        if payment_method == 'bank':
            required_fields = ['account_name', 'account_number', 'routing_number', 'bank_name']
            for field in required_fields:
                if field not in formatted_details:
                    validation_errors[field] = 'This field is required for bank transfers'

        elif payment_method == 'paypal':
            if 'email' not in formatted_details:
                validation_errors['email'] = 'PayPal email is required'
            elif '@' not in formatted_details['email']:
                validation_errors['email'] = 'Enter a valid email address'

        elif payment_method == 'mpesa':
            if 'phone_number' not in formatted_details:
                validation_errors['phone_number'] = 'M-Pesa phone number is required'

        elif payment_method == 'stripe':
            if 'account_id' not in formatted_details:
                validation_errors['account_id'] = 'Stripe account ID is required'

        if validation_errors:
            logger.error(f"Validation failed for payment details: {validation_errors}")
            return Response(
                {'detail': 'Validation failed', 'errors': validation_errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Find or create the payout setting
        try:
            payout_setting = self.get_queryset().get(partner=request.user.partner_profile)
            created = False
            logger.debug(f"Found existing payout setting: {payout_setting}")
        except PayoutSetting.DoesNotExist:
            payout_setting = PayoutSetting(partner=request.user.partner_profile)
            created = True
            logger.debug(f"Created new payout setting for user.")

        # Update the setting
        payout_setting.payment_method = payment_method
        payout_setting.payment_details = formatted_details
        payout_setting.save()

        serializer = self.get_serializer(payout_setting)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )


    def _format_payment_details(self, method, details):
        """Flatten payment details, unwrapping method-specific nesting if present"""
        logger.debug(f"Formatting payment details for method {method} with input: {details}")
        
        # If the method-specific key exists (e.g., {'mpesa': {phone_number: ...}}), unwrap it
        if method in details and isinstance(details[method], dict):
            details = details[method]
            logger.debug(f"Unwrapped nested payment details under '{method}' key: {details}")
        
        # Strip strings and return
        return {k: v.strip() if isinstance(v, str) else v for k, v in details.items()}


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
    def perform_create(self, serializer):
        """Create earnings record with proper initial status based on source"""
        referral = serializer.validated_data.get('referral')
        partner = serializer.validated_data.get('partner')
        amount = serializer.validated_data.get('amount')
        source = serializer.validated_data.get('source', Earnings.Source.REFERRAL)
        
        # Determine initial status based on source type
        initial_status = self._get_initial_status(source, referral)
        
        # Set additional data for the specific source types
        additional_data = {}
        
        if source == Earnings.Source.REFERRAL:
            # For referrals, always set notes about the referral
            client_name = referral.client_name if referral else 'Unknown client'
            additional_data['notes'] = f"Earnings from referral: {client_name}"
        
        # Save with determined status and any additional data
        serializer.save(
            status=initial_status,
            source=source,
            partner=partner,
            amount=amount,
            **additional_data
        )

    def _get_initial_status(self, source, referral=None):
        """
        Determine the initial status for an earnings record
        based on its source and whether it has a referral
        """
        # Referral earnings always need approval
        if source == Earnings.Source.REFERRAL:
            return Earnings.Status.PENDING_APPROVAL
        
        # Your business logic for other source types
        # You can customize this based on your requirements
        if source in [Earnings.Source.PROMOTION]:
            # Promotions may also need approval
            return Earnings.Status.PENDING_APPROVAL
        elif source == Earnings.Source.BONUS:
            # Bonuses might be immediately available or need approval
            # Depending on your business rules
            return Earnings.Status.PENDING_APPROVAL  # or AVAILABLE
        
        # Default for other source types
        return Earnings.Status.AVAILABLE

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Admin approves pending earnings to make them available"""
        if not request.user.is_staff:
            return Response(
                {'error': 'Only admin users can approve earnings'}, 
                status=status.HTTP_403_FORBIDDEN
            )
            
        earning = self.get_object()
        if earning.status != Earnings.Status.PENDING_APPROVAL:
            return Response(
                {'error': 'Only pending approval earnings can be approved'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        earning.status = Earnings.Status.AVAILABLE
        earning.approved_by = request.user
        earning.approval_date = timezone.now()
        earning.save()
        
        serializer = self.get_serializer(earning)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Admin rejects pending earnings"""
        if not request.user.is_staff:
            return Response(
                {'error': 'Only admin users can reject earnings'}, 
                status=status.HTTP_403_FORBIDDEN
            )
            
        earning = self.get_object()
        reason = request.data.get('reason', 'Rejected by admin')
        
        if earning.status != Earnings.Status.PENDING_APPROVAL:
            return Response(
                {'error': 'Only pending approval earnings can be rejected'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        earning.status = Earnings.Status.REJECTED
        earning.notes = f"{earning.notes or ''}\nRejection reason: {reason}"
        earning.rejected_by = request.user
        earning.rejection_date = timezone.now()
        earning.save()
        
        serializer = self.get_serializer(earning)
        return Response(serializer.data)

    @atomic
    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        """Mark an earning as paid when payout is completed"""
        earning = self.get_object()
        
        # Only allow marking as paid if earnings are either AVAILABLE or PAID
        # (prevent marking PENDING_APPROVAL earnings as paid)
        if earning.status not in [Earnings.Status.AVAILABLE, Earnings.Status.PAID]:
            return Response(
                {'error': 'Only available or already paid earnings can be marked as paid'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        payout_id = request.data.get('payout_id')
        if not payout_id:
            return Response(
                {'error': 'Payout ID is required to mark earnings as paid'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            payout = Payout.objects.get(id=payout_id)
        except Payout.DoesNotExist:
            return Response(
                {'error': 'Payout not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Only update if not already paid
        if earning.status != Earnings.Status.PAID:
            earning.status = Earnings.Status.PAID
            earning.payout = payout
            earning.paid_date = timezone.now()
            earning.save()
        
        serializer = self.get_serializer(earning)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get summary of earnings with proper status filtering"""
        queryset = self.get_queryset()
        
        summary_data = {
            'total_earnings': queryset.aggregate(total=Sum('amount'))['total'] or 0,
            'available_earnings': queryset.filter(
                status=Earnings.Status.AVAILABLE
            ).aggregate(total=Sum('amount'))['total'] or 0,
            'pending_approval_earnings': queryset.filter(
                status=Earnings.Status.PENDING_APPROVAL
            ).aggregate(total=Sum('amount'))['total'] or 0,
            'paid_earnings': queryset.filter(
                status=Earnings.Status.PAID
            ).aggregate(total=Sum('amount'))['total'] or 0,
            'rejected_earnings': queryset.filter(
                status=Earnings.Status.REJECTED
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