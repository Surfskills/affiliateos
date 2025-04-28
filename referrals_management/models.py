# referrals/models.py
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from datetime import timedelta
from partner.models import PartnerProfile, Product

class ReferralTimeline(models.Model):
    """Track status changes for referrals"""
    referral = models.ForeignKey(
        'Referral', 
        on_delete=models.CASCADE, 
        related_name='status_changes'
    )
    status = models.CharField(max_length=20)
    timestamp = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='referral_status_changes'
    )

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.referral.client_name} - {self.status} at {self.timestamp}"


class Referral(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        CONTACTED = 'contacted', _('Contacted')
        QUALIFIED = 'qualified', _('Qualified')
        CONVERTED = 'converted', _('Converted')
        REJECTED = 'rejected', _('Rejected')

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='referrals'
    )
    partner = models.ForeignKey(
        PartnerProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='referrals'
    )
    referral_code = models.CharField(max_length=50, db_index=True)
    client_name = models.CharField(max_length=255)
    client_email = models.EmailField()
    client_phone = models.CharField(max_length=50)
    company = models.CharField(max_length=255, blank=True, null=True)
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='referrals'
    )
    product_name = models.CharField(max_length=255, blank=True)
    date_submitted = models.DateTimeField(auto_now_add=True)

    # Keep the original "timeline" choice for frontend
    timeline = models.CharField(
        max_length=20, 
        choices=[
            ('Immediate', 'Immediate'),
            ('1-3 months', '1-3 months'),
            ('3-6 months', '3-6 months'),
            ('6+ months', '6+ months')
        ],
        null=True,
        blank=True
    )
    # Add a proper datetime field for when implementation is expected
    expected_implementation_date = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True
    )
    prev_status = models.CharField(
        max_length=10,
        choices=Status.choices,
        null=True,
        blank=True
    )
    potential_commission = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )
    actual_commission = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True
    )
    budget_range = models.CharField(max_length=50, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_referrals'
    )

    class Meta:
        ordering = ['-date_submitted']
        verbose_name = _("Referral")
        verbose_name_plural = _("Referrals")
        indexes = [
            models.Index(fields=['status', 'date_submitted']),
            models.Index(fields=['referral_code']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['partner']),
        ]

    def __str__(self):
        return f"{self.client_name} ({self.client_email}) - {self.get_status_display()}"

    def save(self, *args, **kwargs):
        # Set partner if not set and user has a partner_profile
        if not self.partner and hasattr(self.user, 'partner_profile'):
            self.partner = self.user.partner_profile

        # Set referral_code if not already set
        if not self.referral_code and self.partner:
            self.referral_code = self.partner.referral_code

        # Set expected implementation date from timeline
        if isinstance(self.timeline, str):
            now = timezone.now()
            if self.timeline == "Immediate":
                self.expected_implementation_date = now
            elif self.timeline == "1-3 months":
                self.expected_implementation_date = now + timedelta(weeks=4)
            elif self.timeline == "3-6 months":
                self.expected_implementation_date = now + timedelta(weeks=12)
            elif self.timeline == "6+ months":
                self.expected_implementation_date = now + timedelta(weeks=24)

        # Track status change
        status_changed = False
        if self.pk:
            old_instance = Referral.objects.get(pk=self.pk)
            if old_instance.status != self.status:
                self.prev_status = old_instance.status
                status_changed = True

        # Set actual commission if status is converted
        if self.status == self.Status.CONVERTED and not self.actual_commission:
            self.actual_commission = self.potential_commission

        super().save(*args, **kwargs)

        # Record timeline entry if status changed
        if status_changed:
            ReferralTimeline.objects.create(
                referral=self,
                status=self.status,
                note=f"Status changed from {self.prev_status} to {self.status}",
                created_by=self.updated_by if hasattr(self, 'updated_by') else None
            )

        # Create earnings if applicable
        if self.status == self.Status.CONVERTED:
            self.create_earning()

    def create_earning(self):
        from payouts.models import Earnings
        if not hasattr(self, 'earning'):
            try:
                if self.partner:
                    return Earnings.objects.create(
                        partner=self.partner,
                        referral=self,
                        amount=self.actual_commission,
                        date=timezone.now().date(),
                        source='referral',
                        status='available' if self.actual_commission > 0 else 'pending'
                    )
            except PartnerProfile.DoesNotExist:
                return None
        return None
