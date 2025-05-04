from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify
import uuid
from django.utils import timezone

class Product(models.Model):
    title = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    description = models.TextField()
    commission = models.CharField(max_length=100)
    price = models.CharField(max_length=100, null=True, blank=True)
    image = models.ImageField(upload_to='products/', null=True, blank=True)
    delivery_time = models.CharField(max_length=100, null=True, blank=True)
    cost = models.CharField(max_length=100, null=True, blank=True)
    support_duration = models.CharField(max_length=100, null=True, blank=True)
    svg_image = models.TextField(null=True, blank=True)  # Store SVG as text
    process_link = models.URLField(max_length=255, null=True, blank=True)
    exclusive = models.CharField(max_length=255, null=True, blank=True)
    booking_path = models.CharField(max_length=255, null=True, blank=True)
    features = models.JSONField(null=True, blank=True)
    category = models.CharField(max_length=100, null=True, blank=True)
    type = models.CharField(max_length=100, null=True, blank=True)
    
    # ✅ Added fields
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    # ✅ Added computed properties
    @property
    def total_referrals(self):
        return self.referrals.count()

    @property
    def converted_referrals(self):
        return self.referrals.filter(status='converted').count()

    @property
    def conversion_rate(self):
        total = self.total_referrals
        return (self.converted_referrals / total) * 100 if total > 0 else 0


class Testimonial(models.Model):
    class TestimonialType(models.TextChoices):
        TEXT = 'text', _('Text')
        IMAGE = 'image', _('Image')
        VIDEO = 'video', _('Video')

    content = models.TextField(null=True, blank=True)
    author = models.CharField(max_length=255)
    role = models.CharField(max_length=255, null=True, blank=True)
    company = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)  # ✅ Added
    is_approved = models.BooleanField(default=False)  # ✅ Added
    type = models.CharField(
        max_length=10,
        choices=TestimonialType.choices,
        default=TestimonialType.TEXT
    )
    image = models.ImageField(
        upload_to='testimonials/images/', 
        null=True, 
        blank=True,
        help_text="Required for image testimonials"
    )
    video = models.FileField(
        upload_to='testimonials/videos/', 
        null=True, 
        blank=True,
        help_text="Required for video testimonials"
    )

    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.author} - {self.get_type_display()} testimonial"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.type == 'image' and not self.image:
            raise ValidationError("Image is required for image testimonials")
        if self.type == 'video' and not self.video:
            raise ValidationError("Video is required for video testimonials")


class PartnerProfile(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        PENDING = 'pending', _('Pending Approval')
        SUSPENDED = 'suspended', _('Suspended')
        DEACTIVATED = 'deactivated', _('Deactivated')

    class Theme(models.TextChoices):
        LIGHT = 'light', _('Light')
        DARK = 'dark', _('Dark')
        BLUE = 'blue', _('Blue')
        GREEN = 'green', _('Green')

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='partner_profile'
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=50)
    company = models.CharField(max_length=255, blank=True, null=True)
    role = models.CharField(max_length=255)
    bio = models.TextField(blank=True)
    profile_photo = models.ImageField(upload_to='profile_photos/', null=True, blank=True)
    referral_code = models.CharField(max_length=50, unique=True, editable=False)
    referral_link = models.CharField(max_length=255, unique=True, editable=False)
    twitter = models.URLField(blank=True, null=True)
    linkedin = models.URLField(blank=True, null=True)
    instagram = models.URLField(blank=True, null=True)
    happy_clients = models.PositiveIntegerField(default=0)
    years_experience = models.PositiveIntegerField(default=0)
    generated_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    support_availability = models.CharField(max_length=50, blank=True, null=True)
    theme = models.CharField(max_length=10, choices=Theme.choices, default=Theme.LIGHT)
    selected_products = models.ManyToManyField(Product, related_name='partners')
    testimonials = models.ManyToManyField(Testimonial, related_name='partners', blank=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    bank_details = models.JSONField(default=dict, blank=True)
    last_login = models.DateTimeField(null=True, blank=True)
    last_login_ip = models.CharField(max_length=45, blank=True, null=True)
    two_factor_enabled = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _("Partner Profile")
        verbose_name_plural = _("Partner Profiles")
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['referral_code']),
            models.Index(fields=['slug']),
        ]

    def __str__(self):
        return f"{self.name} ({self.email})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f"{self.company or self.name}-{uuid.uuid4().hex[:4]}")
        if not self.referral_code:
            self.referral_code = f"REF-{uuid.uuid4().hex[:8].upper()}"
            self.referral_link = f"/ref/{self.referral_code}"
        super().save(*args, **kwargs)

    @property
    def active_products(self):
        return self.selected_products.filter(is_active=True)

    @property
    def approved_testimonials(self):
        return self.testimonials.filter(is_approved=True)
    
    @property
    def total_referrals(self):
        return self.user.referrals.count()
    
    @property
    def pending_referrals(self):
        return self.user.referrals.filter(status='pending').count()
    
    @property
    def converted_referrals(self):
        return self.user.referrals.filter(status='converted').count()
    
    @property
    def conversion_rate(self):
        total = self.total_referrals
        return (self.converted_referrals / total) * 100 if total > 0 else 0
    
    @property
    def available_earnings(self):
        from payouts.models import Earnings
        return Earnings.objects.filter(
            partner=self, 
            status='available'
        ).aggregate(total=models.Sum('amount'))['total'] or 0
    
    @property
    def pending_earnings(self):
        from payouts.models import Earnings
        return Earnings.objects.filter(
            partner=self, 
            status='pending'
        ).aggregate(total=models.Sum('amount'))['total'] or 0
    
    @property
    def total_earnings(self):
        from payouts.models import Earnings
        return Earnings.objects.filter(
            partner=self
        ).exclude(status='cancelled').aggregate(total=models.Sum('amount'))['total'] or 0

    def get_absolute_url(self):
        return f"/partner/{self.slug}/"


class PartnerOnboardingLink(models.Model):
    token = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_onboarding_links'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='used_onboarding_links'
    )
    used_at = models.DateTimeField(null=True, blank=True)

    def is_valid(self):
        return self.is_active and self.expires_at >= timezone.now() and not self.used_by

    def __str__(self):
        return f"Onboarding Link {self.token} ({'active' if self.is_valid() else 'inactive'})"
