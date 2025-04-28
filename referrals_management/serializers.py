from rest_framework import serializers
from .models import Referral, ReferralTimeline

class ReferralTimelineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferralTimeline
        fields = ['id', 'referral', 'status', 'timeline','note', 'timestamp', 'created_by']


class ReferralSerializer(serializers.ModelSerializer):
    class Meta:
        model = Referral
        fields = ['id', 'client_name', 'client_email', 'status', 'timeline', 'notes', 'date_submitted']

class ReferralCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Referral
        fields = '__all__'
        read_only_fields = ['user', 'referral_code', 'actual_commission', 'prev_status', 'updated_at']

    def create(self, validated_data):
        request = self.context.get('request')
        user = request.user

        validated_data['user'] = user

        # Prefer user's referral code
        user_referral_code = getattr(getattr(user, 'partner_profile', None), 'referral_code', None)

        # Fall back to the raw provided referral_code from initial data
        raw_referral_code = self.initial_data.get('referral_code')

        final_referral_code = user_referral_code or raw_referral_code

        if not final_referral_code:
            raise serializers.ValidationError({
                'referral_code': 'Referral code is required because the user has none.'
            })

        validated_data['referral_code'] = final_referral_code

        # Track updater
        validated_data['updated_by'] = user

        return super().create(validated_data)


class ReferralUpdateStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Referral
        fields = ['status', 'timeline', 'notes']

class ReferralListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Referral
        fields = '__all__'
