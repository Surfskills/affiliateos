from rest_framework import serializers
from .models import PartnerOnboardingLink, Product, Testimonial, PartnerProfile
from authentication.models import User
from rest_framework import serializers
from .models import PartnerOnboardingLink, Product, Testimonial, PartnerProfile


class ProductSerializer(serializers.ModelSerializer):
    total_referrals = serializers.ReadOnlyField()
    converted_referrals = serializers.ReadOnlyField()
    conversion_rate = serializers.ReadOnlyField()

    class Meta:
        model = Product
        fields = '__all__'


class TestimonialSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    imageUrl = serializers.SerializerMethodField()
    videoUrl = serializers.SerializerMethodField()

    class Meta:
        model = Testimonial
        fields = [
            'id', 'content', 'author', 'role', 'company', 'created_at',
            'type', 'type_display', 'imageUrl', 'videoUrl'
        ]

    def get_imageUrl(self, obj):
        request = self.context.get('request')
        if obj.image and hasattr(obj.image, 'url'):
            return request.build_absolute_uri(obj.image.url) if request else obj.image.url
        return None

    def get_videoUrl(self, obj):
        request = self.context.get('request')
        if obj.video and hasattr(obj.video, 'url'):
            return request.build_absolute_uri(obj.video.url) if request else obj.video.url
        return None


class PartnerProfileSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    theme_display = serializers.CharField(source='get_theme_display', read_only=True)
    
    selected_products = ProductSerializer(many=True, read_only=True)
    text_testimonials = serializers.SerializerMethodField()
    image_testimonials = serializers.SerializerMethodField()
    video_testimonials = serializers.SerializerMethodField()

    total_referrals = serializers.ReadOnlyField()
    pending_referrals = serializers.ReadOnlyField()
    converted_referrals = serializers.ReadOnlyField()
    conversion_rate = serializers.ReadOnlyField()
    available_earnings = serializers.ReadOnlyField()
    pending_earnings = serializers.ReadOnlyField()
    total_earnings = serializers.ReadOnlyField()

    profile_photo_url = serializers.SerializerMethodField()
    social_links = serializers.SerializerMethodField()

    class Meta:
        model = PartnerProfile
        fields = '__all__'
        read_only_fields = ['referral_code', 'referral_link', 'slug']

    def get_text_testimonials(self, obj):
        return TestimonialSerializer(
            obj.testimonials.filter(type='text', is_approved=True),
            many=True,
            context=self.context
        ).data

    def get_image_testimonials(self, obj):
        return TestimonialSerializer(
            obj.testimonials.filter(type='image', is_approved=True),
            many=True,
            context=self.context
        ).data

    def get_video_testimonials(self, obj):
        return TestimonialSerializer(
            obj.testimonials.filter(type='video', is_approved=True),
            many=True,
            context=self.context
        ).data

    def get_profile_photo_url(self, obj):
        request = self.context.get('request')
        if obj.profile_photo and hasattr(obj.profile_photo, 'url'):
            return request.build_absolute_uri(obj.profile_photo.url) if request else obj.profile_photo.url
        return None

    def get_social_links(self, obj):
        return {
            "twitter": obj.twitter,
            "linkedin": obj.linkedin,
            "instagram": obj.instagram
        }
class PartnerProfileLiteSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = PartnerProfile
        fields ='__all__'
        read_only_fields = ['referral_code', 'slug']


class PartnerOnboardingLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartnerOnboardingLink
        fields = '__all__'
        read_only_fields = ['created_by']
