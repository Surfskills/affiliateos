# payouts/serializers.py
from rest_framework import serializers
from django.db.transaction import atomic
from django.utils import timezone

from partner.models import PartnerProfile
from referrals_management.models import Referral
from referrals_management.serializers import ReferralListSerializer
from .models import Payout, PayoutReferral, PayoutSetting, Earnings


class BasePayoutSerializer(serializers.ModelSerializer):
    """Base serializer with common payout fields"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    processed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Payout
        fields = ['id', 'status', 'status_display', 'payment_method', 'payment_method_display', 
                 'amount', 'request_date', 'processed_date', 'processed_by', 'processed_by_name',
                 'note', 'client_notes', 'transaction_id', 'updated_at']
        read_only_fields = ['id', 'request_date', 'processed_date', 'updated_at']

    def get_processed_by_name(self, obj):
        if obj.processed_by:
            return f"{obj.processed_by.first_name} {obj.processed_by.last_name}".strip() or obj.processed_by.username
        return None


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

    @atomic
    def create(self, validated_data):
        referral_ids = validated_data.pop('referral_ids', [])
        request = self.context.get('request')
        
        # Create the Payout without passing `requested_by` explicitly
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

    def validate_payment_details(self, value):
        payment_method = self.initial_data.get('payment_method')
        required_fields = {
            'bank': ['account_number', 'bank_name'],
            'mpesa': ['phone_number'],
            'paypal': ['email'],
            'stripe': ['account_id']
        }

        if payment_method in required_fields:
            missing = [field for field in required_fields[payment_method] if not value.get(field)]
            if missing:
                raise serializers.ValidationError(
                    f"Missing required fields for {payment_method}: {', '.join(missing)}"
                )
        
        return value



class PayoutUpdateSerializer(BasePayoutSerializer):
    """Serializer for payout updates"""
    class Meta(BasePayoutSerializer.Meta):
        fields = BasePayoutSerializer.Meta.fields + ['transaction_id']

    def update(self, instance, validated_data):
        request = self.context.get('request')
        
        if 'status' in validated_data and validated_data['status'] != instance.status:
            validated_data['processed_by'] = request.user if request else None
            
            if validated_data['status'] == Payout.Status.COMPLETED:
                validated_data['processed_date'] = timezone.now()
                self._mark_earnings_as_paid(instance)
                
        return super().update(instance, validated_data)

    def _mark_earnings_as_paid(self, payout):
        """Mark all processing earnings in this payout as paid"""
        for payout_ref in payout.referrals.select_related('referral__earning').all():
            if hasattr(payout_ref.referral, 'earning') and payout_ref.referral.earning.status == 'processing':
                payout_ref.referral.earning.mark_as_paid()


class PayoutReferralSerializer(serializers.ModelSerializer):
    """Serializer for payout referrals"""
    referral_details = ReferralListSerializer(source='referral', read_only=True)
    
    class Meta:
        model = PayoutReferral
        fields = ['id', 'referral', 'referral_details', 'amount', 'created_at']
        read_only_fields = ['created_at']


class PayoutSettingSerializer(serializers.ModelSerializer):
    """Serializer for payout settings"""
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    schedule_display = serializers.CharField(source='get_payout_schedule_display', read_only=True)
    
    class Meta:
        model = PayoutSetting
        fields = '__all__'
        read_only_fields = ['updated_at']
    
    def validate_payment_details(self, value):
        """Validate payment_details based on payment_method."""
        payment_method = self.initial_data.get('payment_method')
        
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
        return value



class BaseEarningsSerializer(serializers.ModelSerializer):
    """Base serializer with common earnings fields"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    payout_id = serializers.CharField(source='payout.id', read_only=True)

    class Meta:
        model = Earnings
        fields = ['id', 'amount', 'date', 'source', 'source_display', 'status', 'status_display',
                 'notes', 'created_at', 'updated_at', 'payout_id']
        read_only_fields = ['created_at', 'updated_at']


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

    def validate(self, data):
        if data.get('source') != Earnings.Source.REFERRAL and not data.get('date'):
            data['date'] = timezone.now().date()
        return data


class EarningsUpdateSerializer(BaseEarningsSerializer):
    """Serializer for earnings updates"""
    class Meta(BaseEarningsSerializer.Meta):
        fields = ['status', 'notes']