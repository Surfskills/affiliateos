from rest_framework import serializers
from .models import PartnerOnboardingLink, PartnerProfile, Product, Testimonial

class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            'id', 'title', 'name', 'description', 'commission', 'price',
            'image', 'delivery_time', 'support_duration', 'exclusive',
            'category', 'type', 'is_active'
        ]

class TestimonialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Testimonial
        fields = [
            'id', 'content', 'author', 'role', 'company', 'type',
            'image', 'video', 'is_approved'
        ]

class PartnerProfileSerializer(serializers.ModelSerializer):
    # Add calculated fields that match frontend expectations
    total_referrals = serializers.IntegerField(read_only=True)
    converted_referrals = serializers.IntegerField(read_only=True)
    total_earnings = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    available_earnings = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    pending_earnings = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    status_display = serializers.SerializerMethodField()
    conversion_rate = serializers.SerializerMethodField()
    
    # Rename fields to match frontend expectations
    profilePhotoFile = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    
    class Meta:
        model = PartnerProfile
        fields = [
            'id', 'status', 'status_display', 'name', 'email', 'phone',
            'company', 'role', 'bio', 'profilePhotoFile', 'referral_code',
            'referral_link', 'twitter', 'linkedin', 'instagram',
            'happy_clients', 'years_experience', 'generated_revenue',
            'support_availability', 'theme', 'slug', 'createdAt',
            'bank_details', 'last_login', 'two_factor_enabled',
            'total_referrals', 'converted_referrals', 'conversion_rate',
            'total_earnings', 'available_earnings', 'pending_earnings'
        ]
    
    def get_status_display(self, obj):
        return dict(PartnerProfile.Status.choices).get(obj.status)
    
    def get_profilePhotoFile(self, obj):
        if obj.profile_photo:
            return obj.profile_photo.url
        return None
    
    def get_conversion_rate(self, obj):
        total = getattr(obj, 'total_referrals', 0)
        converted = getattr(obj, 'converted_referrals', 0)
        
        if total > 0:
            return round((converted / total) * 100)
        return 0

class PartnerDetailSerializer(PartnerProfileSerializer):
    """
    Extended serializer with additional fields for detailed view
    """
    selected_products = ProductSerializer(many=True, read_only=True)
    testimonials = TestimonialSerializer(many=True, read_only=True)
    
    class Meta(PartnerProfileSerializer.Meta):
        fields = PartnerProfileSerializer.Meta.fields + ['selected_products', 'testimonials']



class PartnerOnboardingLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartnerOnboardingLink
        fields = '__all__'
        read_only_fields = ['created_by']