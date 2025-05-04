from rest_framework import serializers
from .models import PartnerOnboardingLink, PartnerProfile, Product, Testimonial
from rest_framework.response import Response
class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            'id', 'title', 'name', 'description', 'commission', 'price', 
            'image', 'delivery_time', 'cost', 'support_duration',
            'svg_image', 'process_link', 'exclusive', 'booking_path',
            'features', 'category', 'type'
        ]


class TestimonialSerializer(serializers.ModelSerializer):
    imageUrl = serializers.SerializerMethodField(required=False)
    videoUrl = serializers.SerializerMethodField(required=False)
    
    class Meta:
        model = Testimonial
        fields = [
            'id', 'content', 'author', 'role', 'company', 
            'created_at', 'type', 'imageUrl', 'videoUrl'
        ]
    
    def get_imageUrl(self, obj):
        if obj.type == 'image' and obj.image:
            return obj.image.url
        return None
    
    def get_videoUrl(self, obj):
        if obj.type == 'video' and obj.video:
            return obj.video.url
        return None
    
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
    

    selected_products = serializers.SerializerMethodField()
    # Only include the categorized testimonials
    text_testimonials = serializers.SerializerMethodField()
    image_testimonials = serializers.SerializerMethodField()
    video_testimonials = serializers.SerializerMethodField()
    
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
            'total_earnings', 'available_earnings', 'pending_earnings',
            'selected_products', 'text_testimonials', 
            'image_testimonials', 'video_testimonials'
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
        
    def get_text_testimonials(self, obj):
        text_testimonials = obj.testimonials.filter(type='text')
        return TestimonialSerializer(text_testimonials, many=True).data
    
    def get_image_testimonials(self, obj):
        image_testimonials = obj.testimonials.filter(type='image')
        return TestimonialSerializer(image_testimonials, many=True).data
    
    def get_video_testimonials(self, obj):
        video_testimonials = obj.testimonials.filter(type='video')
        return TestimonialSerializer(video_testimonials, many=True).data
    def get_selected_products(self, obj):
        # Explicitly serialize the prefetched products
        products = obj.selected_products.all()
        return ProductSerializer(products, many=True).data
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        print("Serialized data:", serializer.data)  # Inspect output
        return Response(serializer.data)
    
class PartnerProfileCreateSerializer(serializers.ModelSerializer):
    selected_products = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        many=True,
        required=False
    )
    testimonials = serializers.JSONField(write_only=True, required=False)
    
    # File uploads for testimonials
    testimonial_image = serializers.ImageField(write_only=True, required=False)
    testimonial_video = serializers.FileField(write_only=True, required=False)
    
    class Meta:
        model = PartnerProfile
        fields = [
            'name', 'email', 'phone', 'company', 'role', 'bio',
            'profile_photo', 'twitter', 'linkedin', 'instagram',
            'happy_clients', 'years_experience', 'generated_revenue', 
            'support_availability', 'theme',
            'selected_products',
            'testimonials', 'testimonial_image', 'testimonial_video', 
        ]
    
    def create(self, validated_data):
        # Extract and remove nested data
        selected_products = validated_data.pop('selected_products', [])
        testimonials = validated_data.pop('testimonials', [])
        testimonial_image = validated_data.pop('testimonial_image', None)
        testimonial_video = validated_data.pop('testimonial_video', None)
        
        # Get user and remove 'user' from validated_data if it exists
        user = self.context['request'].user
        validated_data.pop('user', None)
        
        # Create the partner profile
        partner_profile = PartnerProfile.objects.create(
            user=user,
            **validated_data
        )
        
        # Add selected products if provided
        if selected_products:
            partner_profile.selected_products.set(selected_products)
        
        # Process testimonials
        try:
            for testimonial in testimonials:
                if testimonial.get('type') == 'text':
                    text_testimonial = Testimonial.objects.create(
                        type='text',
                        content=testimonial.get('content'),
                        author=testimonial.get('author'),
                        role=testimonial.get('role', ''),
                        company=testimonial.get('company', '')
                    )
                    partner_profile.testimonials.add(text_testimonial)
                
                elif testimonial.get('type') == 'image' and testimonial_image:
                    image_testimonial = Testimonial.objects.create(
                        type='image',
                        author=testimonial.get('author'),
                        role=testimonial.get('role', ''),
                        company=testimonial.get('company', ''),
                        image=testimonial_image
                    )
                    partner_profile.testimonials.add(image_testimonial)
                
                elif testimonial.get('type') == 'video' and testimonial_video:
                    video_testimonial = Testimonial.objects.create(
                        type='video',
                        author=testimonial.get('author'),
                        role=testimonial.get('role', ''),
                        company=testimonial.get('company', ''),
                        video=testimonial_video
                    )
                    partner_profile.testimonials.add(video_testimonial)
        except Exception as e:
            print(f"Error processing testimonials: {str(e)}")
        
        return partner_profile

    def get_selected_products(self, obj):
        # This is just to satisfy the SerializerMethodField requirement
        # The actual processing is done in the view
        return []
from django.http import QueryDict

def to_internal_value(self, data):
    # Ensure we can handle both 'selected_products' and 'selectedProducts'
    if 'selectedProducts' in data and 'selected_products' not in data:
        if isinstance(data, QueryDict):
            data = data.copy()  # Safe shallow copy
        else:
            data = dict(data)  # Or just cast to dict if it's already a plain object
        data['selected_products'] = data['selectedProducts']
    
    return super().to_internal_value(data)

class PartnerProfileUpdateSerializer(PartnerProfileCreateSerializer):
    def update(self, instance, validated_data):
        # Extract and remove nested data
        selected_products = validated_data.pop('selected_products', None)
        testimonials = validated_data.pop('testimonials', None)
        testimonial_image = validated_data.pop('testimonial_image', None)
        testimonial_video = validated_data.pop('testimonial_video', None)
        
        # Update profile fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update selected products if provided
        if selected_products is not None:
            try:
                product_ids = [p.get('id') for p in selected_products if p.get('id')]
                products = Product.objects.filter(id__in=product_ids)
                instance.selected_products.set(products)
            except Exception as e:
                print(f"Error updating products: {str(e)}")
        
        # Process testimonials if provided
        if testimonials is not None:
            try:
                # Clear existing testimonials and add new ones
                instance.testimonials.clear()
                
                for testimonial in testimonials:
                    if testimonial.get('type') == 'text':
                        text_testimonial = Testimonial.objects.create(
                            type='text',
                            content=testimonial.get('content'),
                            author=testimonial.get('author'),
                            role=testimonial.get('role', ''),
                            company=testimonial.get('company', '')
                        )
                        instance.testimonials.add(text_testimonial)
                    
                    elif testimonial.get('type') == 'image' and testimonial_image:
                        image_testimonial = Testimonial.objects.create(
                            type='image',
                            author=testimonial.get('author'),
                            role=testimonial.get('role', ''),
                            company=testimonial.get('company', ''),
                            image=testimonial_image
                        )
                        instance.testimonials.add(image_testimonial)
                    
                    elif testimonial.get('type') == 'video' and testimonial_video:
                        video_testimonial = Testimonial.objects.create(
                            type='video',
                            author=testimonial.get('author'),
                            role=testimonial.get('role', ''),
                            company=testimonial.get('company', ''),
                            video=testimonial_video
                        )
                        instance.testimonials.add(video_testimonial)
            except Exception as e:
                print(f"Error updating testimonials: {str(e)}")
        
        return instance

class PartnerDetailSerializer(PartnerProfileSerializer):
    """
    Extended serializer with additional fields for detailed view
    """
    selected_products = ProductSerializer(many=True)
    testimonials = TestimonialSerializer(many=True, read_only=True)
    
    class Meta(PartnerProfileSerializer.Meta):
        fields = PartnerProfileSerializer.Meta.fields + ['selected_products', 'testimonials']



class PartnerOnboardingLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartnerOnboardingLink
        fields = '__all__'
        read_only_fields = ['created_by']