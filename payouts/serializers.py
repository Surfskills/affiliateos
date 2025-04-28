# payouts/serializers.py
from rest_framework import serializers

from partner.serializers import PartnerProfileSerializer
from .models import Payout, PayoutReferral, PayoutSetting, Earnings

from referrals_management.serializers import ReferralListSerializer
from django.db.transaction import atomic

class PayoutReferralSerializer(serializers.ModelSerializer):
    referral_details = ReferralListSerializer(source='referral', read_only=True)
    
    class Meta:
        model = PayoutReferral
        fields = ['id', 'referral', 'referral_details', 'amount', 'created_at']
        read_only_fields = ['created_at']

class PayoutSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    partner_details = PartnerProfileSerializer(source='partner', read_only=True)
    referrals = PayoutReferralSerializer(many=True, read_only=True)
    processed_by_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Payout
        fields = '__all__'
        read_only_fields = ['id', 'request_date', 'processed_date', 'updated_at']
        
    def get_processed_by_name(self, obj):
        if obj.processed_by:
            return f"{obj.processed_by.first_name} {obj.processed_by.last_name}".strip() or obj.processed_by.username
        return None

class PayoutCreateSerializer(serializers.ModelSerializer):
    referral_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    
    class Meta:
        model = Payout
        fields = ['partner', 'payment_method', 'payment_details', 'note', 'referral_ids']
        
    @atomic
    def create(self, validated_data):
        referral_ids = validated_data.pop('referral_ids', [])
        request = self.context.get('request')
        user = request.user if request else None
        
        # Create the payout instance
        payout = Payout.objects.create(**validated_data)
        
        # Process referrals
        from referrals_management.models import Referral
        total_amount = 0
        
        if referral_ids:
            # Get referrals with available earnings
            referrals = Referral.objects.filter(
                id__in=referral_ids,
                status='converted',
                earning__status='available'
            )
            
            for referral in referrals:
                if hasattr(referral, 'earning'):
                    # Create payout referral link
                    amount = referral.earning.amount
                    PayoutReferral.objects.create(
                        payout=payout,
                        referral=referral,
                        amount=amount
                    )
                    
                    # Update earning status
                    referral.earning.mark_as_processing(payout)
                    
                    # Add to total amount
                    total_amount += amount
        
        # Update payout amount with total
        payout.amount = total_amount
        payout.save()
        
        return payout

class PayoutUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payout
        fields = ['status', 'payment_method', 'payment_details', 'note', 'transaction_id']
        
    def update(self, instance, validated_data):
        request = self.context.get('request')
        user = request.user if request else None
        
        # Set who processed the payout
        if user and 'status' in validated_data:
            if validated_data['status'] != instance.status:
                validated_data['processed_by'] = user
                
                # If completed, set processed date
                if validated_data['status'] == Payout.Status.COMPLETED:
                    from django.utils import timezone
                    validated_data['processed_date'] = timezone.now()
                    
                    # Update earnings status
                    for payout_ref in instance.referrals.all():
                        if hasattr(payout_ref.referral, 'earning'):
                            earning = payout_ref.referral.earning
                            if earning.status == 'processing':
                                earning.mark_as_paid()
                                
        return super().update(instance, validated_data)

class PayoutSettingSerializer(serializers.ModelSerializer):
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    schedule_display = serializers.ReadOnlyField()
    
    class Meta:
        model = PayoutSetting
        fields = '__all__'
        read_only_fields = ['updated_at']

class EarningsSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    partner_name = serializers.CharField(source='partner.name', read_only=True)
    referral_details = serializers.SerializerMethodField(read_only=True)
    payout_id = serializers.CharField(source='payout.id', read_only=True)
    
    class Meta:
        model = Earnings
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']
        
    def get_referral_details(self, obj):
        if obj.referral:
            return {
                'id': obj.referral.id,
                'client_name': obj.referral.client_name,
                'product': obj.referral.product.name if obj.referral.product else None,
                'status': obj.referral.status
            }
        return None

class EarningsCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Earnings
        fields = ['partner', 'amount', 'date', 'source', 'status', 'notes']
        
    def validate(self, data):
        if data.get('source') != Earnings.Source.REFERRAL and not data.get('date'):
            from django.utils import timezone
            data['date'] = timezone.now().date()
        return data

class EarningsUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Earnings
        fields = ['status', 'notes']