from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from .models import PartnerOnboardingLink, Product, Testimonial, PartnerProfile
from django.utils.html import format_html
from django.db.models import Count, Sum

class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'category',
        'type',
        'commission_display',
        'price_display',
        'is_active',
        'total_referrals',
        'converted_referrals',
        'conversion_rate_display'
    )
    list_filter = (
        'is_active',
        'category',
        'type',
        'exclusive'
    )
    search_fields = (
        'name',
        'title',
        'description',
        'category'
    )
    readonly_fields = (
        'total_referrals',
        'converted_referrals',
        'conversion_rate_display',
        'created_at',
        'updated_at'
    )
    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'title',
                'name',
                'description',
                'category',
                'type'
            )
        }),
        (_('Pricing & Commission'), {
            'fields': (
                'price',
                'cost',
                'commission'
            )
        }),
        (_('Visuals'), {
            'fields': (
                'image',
                'svg_image'
            ),
            'classes': ('collapse',)
        }),
        (_('Features & Settings'), {
            'fields': (
                'features',
                'delivery_time',
                'support_duration',
                'process_link',
                'booking_path',
                'exclusive',
                'is_active'
            )
        }),
        (_('Statistics'), {
            'fields': (
                'total_referrals',
                'converted_referrals',
                'conversion_rate_display'
            )
        }),
        (_('Timestamps'), {
            'fields': (
                'created_at',
                'updated_at'
            ),
            'classes': ('collapse',)
        }),
    )
    list_editable = ('is_active',)
    actions = ['activate_products', 'deactivate_products']

    def commission_display(self, obj):
        return f"{obj.commission}%"
    commission_display.short_description = _('Commission')

    def price_display(self, obj):
        return f"${obj.price}" if obj.price else "-"
    price_display.short_description = _('Price')

    def conversion_rate_display(self, obj):
        return f"{obj.conversion_rate:.1f}%"
    conversion_rate_display.short_description = _('Conversion Rate')

    def activate_products(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} products activated")
    activate_products.short_description = _("Activate selected products")

    def deactivate_products(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} products deactivated")
    deactivate_products.short_description = _("Deactivate selected products")

class TestimonialAdmin(admin.ModelAdmin):
   class TestimonialAdmin(admin.ModelAdmin):
    list_display = (
        'author',
        'company_role_display',
        'type_display',
        'status',  # ✅ replaces is_approved
        'created_at',
    )
    list_filter = (
        'type',
        'status',  # ✅ replaces is_approved
        'created_at',
    )
    search_fields = (
        'author',
        'company',
        'role',
        'content',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
        'media_preview',
    )
    fieldsets = (
        (_('Content'), {
            'fields': (
                'content',
                'type',
                'image',
                'video',
                'media_preview',
            )
        }),
        (_('Author Information'), {
            'fields': (
                'author',
                'role',
                'company',
            )
        }),
        (_('Settings'), {
            'fields': (
                'status',  # ✅ replaces is_approved
            )
        }),
        (_('Timestamps'), {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',)
        }),
    )
    list_editable = ('status',)  # ✅ replaces is_approved
    actions = ['approve_testimonials', 'reject_testimonials']

    def type_display(self, obj):
        return obj.get_type_display()
    type_display.short_description = _('Type')

    def company_role_display(self, obj):
        parts = []
        if obj.company:
            parts.append(obj.company)
        if obj.role:
            parts.append(obj.role)
        return " | ".join(parts) if parts else "-"
    company_role_display.short_description = _('Company/Role')

    def media_preview(self, obj):
        if obj.type == 'image' and obj.image:
            return format_html('<img src="{}" style="max-height: 200px;"/>', obj.image.url)
        elif obj.type == 'video' and obj.video:
            return format_html(
                '<video width="320" height="240" controls><source src="{}" type="video/mp4">Your browser does not support the video tag.</video>',
                obj.video.url
            )
        return "-"
    media_preview.short_description = _('Media Preview')

    def approve_testimonials(self, request, queryset):
        updated = queryset.update(status=Testimonial.Status.APPROVED)
        self.message_user(request, f"{updated} testimonial(s) approved.")
    approve_testimonials.short_description = _("Approve selected testimonials")

    def reject_testimonials(self, request, queryset):
        updated = queryset.update(status=Testimonial.Status.REJECTED)
        self.message_user(request, f"{updated} testimonial(s) rejected.")
    reject_testimonials.short_description = _("Reject selected testimonials")

class PartnerProfileAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'email',
        'company',
        'status_display',
        'total_referrals',
        'converted_referrals',
        'conversion_rate_display',
        'available_earnings_display',
        'created_at'
    )
    list_filter = (
        'status',
        'theme',
        'created_at'
    )
    search_fields = (
        'name',
        'email',
        'company',
        'referral_code',
        'user__email'
    )
    readonly_fields = (
        'referral_code',
        'referral_link',
        'slug',
        'total_referrals',
        'pending_referrals',
        'converted_referrals',
        'conversion_rate_display',
        'available_earnings_display',
        'pending_earnings_display',
        'total_earnings_display',
        'created_at',
        'updated_at',
        'profile_photo_preview'
    )
    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'user',
                'status',
                'name',
                'email',
                'phone'
            )
        }),
        (_('Professional Information'), {
            'fields': (
                'company',
                'role',
                'bio',
                'happy_clients',
                'years_experience',
                'generated_revenue',
                'support_availability'
            )
        }),
        (_('Profile Settings'), {
            'fields': (
                'profile_photo',
                'profile_photo_preview',
                'theme',
                'selected_products',
                'testimonials'
            )
        }),
        (_('Social & Links'), {
            'fields': (
                'twitter',
                'linkedin',
                'instagram',
                'referral_code',
                'referral_link',
                'slug'
            ),
            'classes': ('collapse',)
        }),
        (_('Statistics'), {
            'fields': (
                'total_referrals',
                'pending_referrals',
                'converted_referrals',
                'conversion_rate_display',
                'available_earnings_display',
                'pending_earnings_display',
                'total_earnings_display'
            )
        }),
        (_('Timestamps'), {
            'fields': (
                'created_at',
                'updated_at'
            ),
            'classes': ('collapse',)
        }),
    )
    filter_horizontal = ('selected_products', 'testimonials')
    actions = ['activate_partners', 'suspend_partners', 'deactivate_partners']

    def status_display(self, obj):
        return obj.get_status_display()
    status_display.short_description = _('Status')

    def conversion_rate_display(self, obj):
        return f"{obj.conversion_rate:.1f}%"
    conversion_rate_display.short_description = _('Conversion Rate')

    def available_earnings_display(self, obj):
        return f"${obj.available_earnings:,.2f}"
    available_earnings_display.short_description = _('Available Earnings')

    def pending_earnings_display(self, obj):
        return f"${obj.pending_earnings:,.2f}"
    pending_earnings_display.short_description = _('Pending Earnings')

    def total_earnings_display(self, obj):
        return f"${obj.total_earnings:,.2f}"
    total_earnings_display.short_description = _('Total Earnings')

    def profile_photo_preview(self, obj):
        if obj.profile_photo:
            return format_html('<img src="{}" style="max-height: 200px;"/>', obj.profile_photo.url)
        return "-"
    profile_photo_preview.short_description = _('Profile Photo Preview')

    def activate_partners(self, request, queryset):
        updated = queryset.update(status='active')
        self.message_user(request, f"{updated} partners activated")
    activate_partners.short_description = _("Activate selected partners")

    def suspend_partners(self, request, queryset):
        updated = queryset.update(status='suspended')
        self.message_user(request, f"{updated} partners suspended")
    suspend_partners.short_description = _("Suspend selected partners")

    def deactivate_partners(self, request, queryset):
        updated = queryset.update(status='deactivated')
        self.message_user(request, f"{updated} partners deactivated")
    deactivate_partners.short_description = _("Deactivate selected partners")
    
class PartnerOnboardingLinkAdmin(admin.ModelAdmin):
    list_display = (
        'token',
        'created_by',
        'created_at',
        'expires_at',
        'is_active',
        'used_by',
        'used_at',
        'is_valid_display'
    )
    list_filter = ('is_active', 'created_at', 'expires_at')
    search_fields = ('token', 'created_by__email', 'used_by__email')
    readonly_fields = ('created_at', 'used_at', 'is_valid_display')

    def is_valid_display(self, obj):
        return obj.is_valid()
    is_valid_display.short_description = 'Is Valid'
    is_valid_display.boolean = True

admin.site.register(PartnerOnboardingLink, PartnerOnboardingLinkAdmin)
admin.site.register(Product, ProductAdmin)
admin.site.register(Testimonial, TestimonialAdmin)
admin.site.register(PartnerProfile, PartnerProfileAdmin)