# payouts/serializers.py
from rest_framework import serializers
from django.db.transaction import atomic
from django.utils import timezone
from django.db.models import Q
from partner.models import PartnerProfile
from referrals_management.models import Referral
from referrals_management.serializers import ReferralListSerializer
from .models import Payout, PayoutReferral, PayoutSetting, Earnings
from django.db import transaction
import re


class BasePayoutSerializer(serializers.ModelSerializer):
    """Base serializer with common payout fields"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    processed_by_name = serializers.SerializerMethodField()
    formatted_payment_details = serializers.SerializerMethodField()

    class Meta:
        model = Payout
        fields = ['id', 'status', 'status_display', 'payment_method',  'payment_method_display', 
                 'amount', 'request_date', 'processed_date', 'processed_by', 'processed_by_name',
                 'note', 'client_notes', 'transaction_id', 'updated_at', 'formatted_payment_details']
        read_only_fields = ['id', 'request_date', 'processed_date', 'updated_at']

    def get_processed_by_name(self, obj):
        if obj.processed_by:
            return f"{obj.processed_by.first_name} {obj.processed_by.last_name}".strip() or obj.processed_by.username
        return None
        
    def get_formatted_payment_details(self, obj):
        """Format payment details based on payment method for consistent display"""
        details = obj.payment_details or {}
        method = obj.payment_method
        
        # Format based on payment method
        if method == 'paypal':
            return {
                'email': details.get('email', '')
            }
        elif method == 'bank':
            return {
                'account_name': details.get('account_name', ''),
                'account_number': details.get('account_number', ''),
                'routing_number': details.get('routing_number', ''),
                'bank_name': details.get('bank_name', '')
            }
        elif method == 'mpesa':
            return {
                'phone_number': details.get('phone_number', '')
            }
        elif method == 'stripe':
            return {
                'account_id': details.get('account_id', '')
            }
        elif method == 'crypto':
            return {
                'wallet_address': details.get('wallet_address', ''),
                'currency': details.get('currency', '')
            }
        return details


class PayoutSerializer(BasePayoutSerializer):
    """Serializer for payout read operations"""
    partner_details = serializers.SerializerMethodField()
    referrals = serializers.SerializerMethodField()

    class Meta(BasePayoutSerializer.Meta):
        fields = BasePayoutSerializer.Meta.fields + ['partner_details', 'referrals']

    def get_partner_details(self, obj):
        from partner.serializers import PartnerProfileSerializer
        return PartnerProfileSerializer(obj.partner).data

    def get_referrals(self, obj):
        return PayoutReferralSerializer(obj.referrals.all(), many=True).data


class PayoutCreateSerializer(BasePayoutSerializer):
    """Serializer for payout creation"""
    referral_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    partner = serializers.PrimaryKeyRelatedField(
        queryset=PartnerProfile.objects.all(),
        required=False,
        help_text="Partner ID (required for staff users only)"
    )
    payment_details = serializers.JSONField(required=True)

    class Meta(BasePayoutSerializer.Meta):
        fields = BasePayoutSerializer.Meta.fields + ['partner', 'payment_details', 'referral_ids']
        read_only_fields = BasePayoutSerializer.Meta.read_only_fields + ['status']

    def validate(self, data):
        request = self.context.get('request')
        
        # For non-staff users, automatically set their partner profile
        if request and not request.user.is_staff:
            if not hasattr(request.user, 'partner_profile'):
                raise serializers.ValidationError(
                    "User does not have an associated partner profile",
                    code='no_partner_profile'
                )
            data['partner'] = request.user.partner_profile
        
        # For staff users, partner is required if not provided
        elif request and request.user.is_staff and 'partner' not in data:
            raise serializers.ValidationError(
                "Partner ID is required for staff users",
                code='partner_required'
            )
        
        return data

    def validate_payment_details(self, value):
        """Normalize and validate payment details"""
        # Normalize keys to snake_case if they came in camelCase
        def camel_to_snake(s): return re.sub(r'(?<!^)(?=[A-Z])', '_', s).lower()
        value = {camel_to_snake(k): v for k, v in value.items()}
        
        payment_method = self.initial_data.get('payment_method')
        required_fields = {
            'bank': ['account_number', 'bank_name', 'account_name', 'routing_number'],
            'mpesa': ['phone_number'],
            'paypal': ['email'],
            'stripe': ['account_id'],
            'crypto': ['wallet_address', 'currency']
        }

        if payment_method in required_fields:
            missing = [field for field in required_fields[payment_method] if not value.get(field)]
            if missing:
                raise serializers.ValidationError(
                    f"Missing required fields for {payment_method}: {', '.join(missing)}"
                )
        
        return value

    @atomic
    def create(self, validated_data):
        referral_ids = validated_data.pop('referral_ids', [])
        request = self.context.get('request')
        
        # Set requested_by if not explicitly provided
        if 'requested_by' not in validated_data and request:
            validated_data['requested_by'] = request.user
        
        # Create the Payout
        payout = Payout.objects.create(**validated_data)

        # Process referrals if provided
        if referral_ids:
            total_amount = 0
            referrals = Referral.objects.filter(
                id__in=referral_ids,
                status='converted',
                earning__status='available'
            ).select_related('earning')

            for referral in referrals:
                if hasattr(referral, 'earning'):
                    amount = referral.earning.amount
                    PayoutReferral.objects.create(
                        payout=payout,
                        referral=referral,
                        amount=amount
                    )
                    referral.earning.mark_as_processing(payout)
                    total_amount += amount

            payout.amount = total_amount
            payout.save()

        return payout


class PayoutUpdateSerializer(BasePayoutSerializer):
    """Serializer for payout updates"""
    class Meta(BasePayoutSerializer.Meta):
        fields = BasePayoutSerializer.Meta.fields + ['transaction_id']

    def update(self, instance, validated_data):
        request = self.context.get('request')
        
        # Track if status is being changed to COMPLETED
        completing_payout = (
            'status' in validated_data and 
            validated_data['status'] == Payout.Status.COMPLETED and
            instance.status != Payout.Status.COMPLETED
        )
        
        if 'status' in validated_data and validated_data['status'] != instance.status:
            validated_data['processed_by'] = request.user if request else None
            
            if validated_data['status'] == Payout.Status.COMPLETED:
                validated_data['processed_date'] = timezone.now()
                
        # Update the instance
        try:
            with transaction.atomic():
                instance = super().update(instance, validated_data)
                
                # After updating, if status changed to COMPLETED, update earnings
                if completing_payout:
                    instance._update_associated_earnings()
        except Exception as e:
  
            raise
            
        return instance

    def _mark_all_earnings_as_paid(self, payout):
        """Mark all earnings associated with this payout as paid"""
        # Update earnings from payout referrals
        for payout_ref in payout.referrals.select_related('referral__earning').all():
            if hasattr(payout_ref.referral, 'earning'):
                earning = payout_ref.referral.earning
                if earning.status in [Earnings.Status.PROCESSING, Earnings.Status.AVAILABLE]:
                    earning.status = Earnings.Status.PAID
                    earning.payout = payout
                    earning.paid_date = timezone.now()
                    earning.save()
        
        # Directly update any earnings linked to the payout
        for earning in payout.earnings_included.all():
            if earning.status in [Earnings.Status.PROCESSING, Earnings.Status.AVAILABLE]:
                earning.status = Earnings.Status.PAID
                earning.paid_date = timezone.now()
                earning.save()

    def _ensure_all_earnings_paid(self, payout):
        """Safety check to ensure all related earnings are marked as paid"""
        from .models import Earnings
        
        # Find any earnings that should be paid but aren't
        unpaid_earnings = Earnings.objects.filter(
            Q(payout=payout) | Q(referral__payout_referrals__payout=payout),
            status__in=[Earnings.Status.AVAILABLE, Earnings.Status.PROCESSING]
        ).distinct()
        
        for earning in unpaid_earnings:
            earning.status = Earnings.Status.PAID
            earning.paid_date = timezone.now()
            earning.save()

class PayoutReferralSerializer(serializers.ModelSerializer):
    """Serializer for payout referrals"""
    referral_details = ReferralListSerializer(source='referral', read_only=True)
    
    class Meta:
        model = PayoutReferral
        fields = ['id', 'referral', 'referral_details', 'amount', 'created_at']
        read_only_fields = ['created_at']


from rest_framework import serializers
from .models import PayoutSetting


class PayoutSettingSerializer(serializers.ModelSerializer):
    """Serializer for payout settings"""
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    schedule_display = serializers.CharField(source='get_payout_schedule_display', read_only=True)
    # Add a formatted payment details field that will be included in responses
    formatted_payment_details = serializers.SerializerMethodField()
    class Meta:
        model = PayoutSetting
        fields = '__all__'
        read_only_fields = ['updated_at']

    def get_formatted_payment_details(self, obj):
        """Format payment details based on payment method for consistent display"""
        details = obj.payment_details or {}
        method = obj.payment_method
        
        # Format based on payment method
        if method == 'paypal':
            return {
                'email': details.get('email', '')
            }
        elif method == 'bank':
            return {
                'account_name': details.get('account_name', ''),
                'account_number': details.get('account_number', ''),
                'routing_number': details.get('routing_number', ''),
                'bank_name': details.get('bank_name', '')
            }
        elif method == 'mpesa':
            return {
                'phone_number': details.get('phone_number', '')
            }
        elif method == 'stripe':
            return {
                'account_id': details.get('account_id', '')
            }
        elif method == 'crypto':
            return {
                'wallet_address': details.get('wallet_address', ''),
                'currency': details.get('currency', '')
            }
        return details

    def validate_payment_details(self, value):
        # Normalize keys to snake_case if they came in camelCase
        def camel_to_snake(s): return re.sub(r'(?<!^)(?=[A-Z])', '_', s).lower()
        value = {camel_to_snake(k): v for k, v in value.items()}

        payment_method = self.initial_data.get('payment_method')
        if not payment_method:
            raise serializers.ValidationError("Payment method must be specified.")

        if payment_method == 'paypal':
            if not value.get('email'):
                raise serializers.ValidationError("Paypal email is required.")
        elif payment_method == 'bank':
            required_fields = ['account_name', 'account_number', 'routing_number', 'bank_name']
            for field in required_fields:
                if not value.get(field):
                    raise serializers.ValidationError(f"Bank details require the field: {field}.")
        elif payment_method == 'mpesa':
            if not value.get('phone_number'):
                raise serializers.ValidationError("M-Pesa requires a phone number.")
        elif payment_method == 'stripe':
            if not value.get('account_id'):
                raise serializers.ValidationError("Stripe requires an account ID.")
        elif payment_method == 'crypto':
            if not value.get('wallet_address'):
                raise serializers.ValidationError("Cryptocurrency payments require a wallet address.")
        else:
            raise serializers.ValidationError(f"Unsupported payment method: {payment_method}")

        return value


class BaseEarningsSerializer(serializers.ModelSerializer):
    """Base serializer with common earnings fields"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    payout_id = serializers.CharField(source='payout.id', read_only=True)
    status = serializers.CharField(read_only=True)
    raw_status = serializers.CharField(source='status', read_only=True)
    approved_by = serializers.CharField(source='approved_by.username', read_only=True)
    rejected_by = serializers.CharField(source='rejected_by.username', read_only=True)

    class Meta:
        model = Earnings
        fields = [
            'id', 'amount', 'date', 'source','paid_date', 'source_display',
            'status', 'raw_status', 'status_display', 'notes',
            'created_at', 'updated_at', 'payout_id',
            'approved_by', 'approval_date', 'rejected_by', 'rejection_date'
        ]
        read_only_fields = [
            'created_at', 'updated_at',
            'approved_by', 'approval_date',
            'rejected_by', 'rejection_date'
        ]


class EarningsSerializer(BaseEarningsSerializer):
    """Serializer for earnings read operations"""
    partner_name = serializers.CharField(source='partner.name', read_only=True)
    referral_details = serializers.SerializerMethodField()

    class Meta(BaseEarningsSerializer.Meta):
        fields = BaseEarningsSerializer.Meta.fields + ['partner_name', 'referral_details']

    def get_referral_details(self, obj):
        if obj.referral:
            return {
                'id': obj.referral.id,
                'client_name': obj.referral.client_name,
                'product': obj.referral.product.name if obj.referral.product else None,
                'status': obj.referral.status
            }
        return None


class EarningsCreateSerializer(BaseEarningsSerializer):
    """Serializer for earnings creation"""

    class Meta(BaseEarningsSerializer.Meta):
        fields = BaseEarningsSerializer.Meta.fields + ['partner', 'referral']
        read_only_fields = BaseEarningsSerializer.Meta.read_only_fields

    def validate(self, data):
        """Enhanced validation to ensure proper status assignment based on source"""
        # Set default date if not provided
        if not data.get('date'):
            data['date'] = timezone.now().date()
        
        # Make sure source is set, defaulting to REFERRAL if not specified
        source = data.get('source', Earnings.Source.REFERRAL)
        data['source'] = source
        
        # We'll let the ViewSet's perform_create handle the status assignment
        # but we can add some validation here to ensure data consistency
        
        # If referral is provided, source must be REFERRAL
        referral = data.get('referral')
        if referral and source != Earnings.Source.REFERRAL:
            raise serializers.ValidationError(
                "When a referral is provided, source must be 'referral'"
            )
        
        return data


class EarningsUpdateSerializer(serializers.ModelSerializer):
    """Serializer for earnings updates"""
    
    class Meta:
        model = Earnings
        fields = ['notes']  # Removed 'status' to prevent direct status changes
        
    def validate(self, data):
        """Prevent unauthorized status changes"""
        # Status changes should only happen through dedicated endpoints like 
        # approve(), reject(), mark_paid(), etc.
        if 'status' in self.initial_data:
            raise serializers.ValidationError(
                "Status cannot be directly changed. Use the appropriate endpoint instead."
            )
        return data