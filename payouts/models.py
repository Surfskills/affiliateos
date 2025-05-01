from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from decimal import Decimal
from partner.models import PartnerProfile
from referrals_management.models import Referral
import uuid
from django.db.models import Sum
from django.core.exceptions import ValidationError
class PayoutTimeline(models.Model):
    """Track status changes for payouts"""
    payout = models.ForeignKey(
        'Payout',
        on_delete=models.CASCADE,
        related_name='status_changes'
    )
    status = models.CharField(max_length=20)
    timestamp = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True, null=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payout_status_changes'
    )

    class Meta:
        ordering = ['-timestamp']
        verbose_name = _("Payout Timeline")
        verbose_name_plural = _("Payout Timelines")

    def __str__(self):
        return f"{self.payout.id} - {self.status} at {self.timestamp}"

class Payout(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        PROCESSING = 'processing', _('Processing')
        COMPLETED = 'completed', _('Completed')
        FAILED = 'failed', _('Failed')
        CANCELLED = 'cancelled', _('Cancelled')
    
    class PaymentMethod(models.TextChoices):
        BANK = 'bank', _('Bank Transfer')
        PAYPAL = 'paypal', _('PayPal')
        STRIPE = 'stripe', _('Stripe')
        MPESA = 'mpesa', _('M-Pesa')
        CRYPTO = 'crypto', _('Cryptocurrency')

    id = models.CharField(primary_key=True, max_length=20, editable=False)
    partner = models.ForeignKey(
        PartnerProfile,
        on_delete=models.PROTECT,
        related_name='payouts',
        help_text="The partner receiving this payout"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requested_payouts',
        help_text="User who requested this payout"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING, db_index=True)
    request_date = models.DateTimeField(auto_now_add=True)
    processed_date = models.DateTimeField(null=True, blank=True)
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices)
    payment_details = models.JSONField(default=dict)
    transaction_id = models.CharField(max_length=100, null=True, blank=True)
    note = models.TextField(blank=True, null=True, help_text="Internal notes for this payout")
    client_notes = models.TextField(blank=True, null=True, help_text="Notes visible to the partner")
    updated_at = models.DateTimeField(auto_now=True)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_payouts',
        help_text="Admin who processed this payout"
    )

    class Meta:
        ordering = ['-request_date']
        verbose_name = _("Payout")
        verbose_name_plural = _("Payouts")
        indexes = [
            models.Index(fields=['status', 'request_date']),
            models.Index(fields=['partner', 'status']),
        ]

    def __str__(self):
        return f"{self.id} - {self.partner.name} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        # Auto-connect partner to user if not set
        if not self.partner and hasattr(self.requested_by, 'partner_profile'):
            self.partner = self.requested_by.partner_profile

        # Generate ID if not exists
        if not self.id:
            self.id = f"PY-{uuid.uuid4().hex[:8].upper()}"

        status_changed = False

        if self.pk and Payout.objects.filter(pk=self.pk).exists():
            old_instance = Payout.objects.get(pk=self.pk)
            if old_instance.status != self.status:
                status_changed = True

        super().save(*args, **kwargs)

        # After saving, create a timeline record if the status changed
        if status_changed:
            PayoutTimeline.objects.create(
                payout=self,
                status=self.status,
                note=f"Status changed to {self.status}",
                changed_by=self.processed_by
            )


    def process(self, user=None):
        self.status = self.Status.PROCESSING
        self.processed_by = user
        self.save()
        return self
        
    def complete(self, transaction_id=None, user=None):
            self.status = self.Status.COMPLETED
            self.processed_date = timezone.now()
            self.transaction_id = transaction_id
            self.processed_by = user if user else self.processed_by
            self.save()
            
            # Update associated earnings to PAID status
            for earning in self.earnings_included.all():
                if earning.status == Earnings.Status.PROCESSING:
                    earning.mark_as_paid()
            
            return self
    
    def cancel(self, reason=None, user=None):
        self.status = self.Status.CANCELLED
        if reason:
            self.note = f"{self.note or ''}\nCancellation reason: {reason}"
        self.processed_by = user if user else self.processed_by
        self.save()
        
        # Reset earnings status to available if payout is cancelled
        for earning in self.earnings_included.all():
            if earning.status == Earnings.Status.PROCESSING:
                earning.status = Earnings.Status.AVAILABLE
                earning.payout = None
                earning.save()
                
        return self

    def fail(self, error_message, user=None):
        self.status = self.Status.FAILED
        self.note = f"{self.note or ''}\nError: {error_message}"
        self.processed_by = user if user else self.processed_by
        self.save()
        return self
        
        
    @property
    def can_process(self):
        return self.status == self.Status.PENDING
        
    @property
    def can_complete(self):
        return self.status == self.Status.PROCESSING
        
    @property
    def can_cancel(self):
        return self.status in [self.Status.PENDING, self.Status.PROCESSING]
    
    def get_status_history(self):
        return self.status_changes.order_by('-timestamp')
    
    def get_earnings_summary(self):
        return {
            'total': self.earnings_included.aggregate(Sum('amount'))['amount__sum'] or 0,
            'count': self.earnings_included.count()
        }

class PayoutReferral(models.Model):
    payout = models.ForeignKey(Payout, on_delete=models.CASCADE, related_name='referrals')
    referral = models.ForeignKey(Referral, on_delete=models.CASCADE, related_name='payout_referrals')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['payout', 'referral']
        verbose_name = _("Payout Referral")
        verbose_name_plural = _("Payout Referrals")
        
    def __str__(self):
        return f"{self.payout.id} - {self.referral.client_name} (${self.amount})"

class PayoutSetting(models.Model):
    partner = models.OneToOneField(
        PartnerProfile,
        on_delete=models.CASCADE,
        related_name='payout_setting'
    )
    payment_method = models.CharField(
        max_length=10,
        choices=Payout.PaymentMethod.choices,
        default=Payout.PaymentMethod.BANK
    )
    payment_details = models.JSONField(default=dict)
    minimum_payout_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('50.00')
    )
    auto_payout = models.BooleanField(default=False)
    payout_schedule = models.CharField(
        max_length=20,
        choices=[
            ('manual', _('Manual')),
            ('weekly', _('Weekly')),
            ('biweekly', _('Bi-Weekly')),
            ('monthly', _('Monthly')),
            ('quarterly', _('Quarterly'))
        ],
        default='monthly'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Payout Setting")
        verbose_name_plural = _("Payout Settings")
        
    def __str__(self):
        return f"{self.partner.name} - {self.get_payment_method_display()}"
        
    @property
    def payment_method_display(self):
        return self.get_payment_method_display()
        
    @property
    def schedule_display(self):
        return dict(self._meta.get_field('payout_schedule').choices)[self.payout_schedule]
    
    def clean(self):
        """Custom validation to ensure payment_details are valid based on payment_method."""
        if self.payment_method == 'paypal':
            if not self.payment_details.get('email'):
                raise ValidationError("Paypal email is required in payment_details.")
        elif self.payment_method == 'bank':
            required_fields = ['account_name', 'account_number', 'routing_number', 'bank_name']
            for field in required_fields:
                if not self.payment_details.get(field):
                    raise ValidationError(f"Bank details require the field: {field}.")
        elif self.payment_method == 'mpesa':
            if not self.payment_details.get('phone_number'):
                raise ValidationError("M-Pesa requires a phone number in payment_details.")
        elif self.payment_method == 'stripe':
            if not self.payment_details.get('account_id'):
                raise ValidationError("Stripe requires an account ID in payment_details.")
        super().clean()

class Earnings(models.Model):
    class Source(models.TextChoices):
        REFERRAL = 'referral', _('Referral')
        BONUS = 'bonus', _('Bonus')
        PROMOTION = 'promotion', _('Promotion')
        OTHER = 'other', _('Other')

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        AVAILABLE = 'available', _('Available')
        PROCESSING = 'processing', _('Processing')
        PAID = 'paid', _('Paid')
        CANCELLED = 'cancelled', _('Cancelled')

    partner = models.ForeignKey(
        PartnerProfile,
        on_delete=models.CASCADE,
        related_name='earnings'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_earnings'
    )
    referral = models.OneToOneField(
        Referral,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='earning'
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.REFERRAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    payout = models.ForeignKey(
        Payout,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='earnings_included'
    )

    class Meta:
        ordering = ['-date']
        verbose_name_plural = _("Earnings")
        indexes = [
            models.Index(fields=['status', 'date']),
            models.Index(fields=['partner', 'status']),
        ]

    def __str__(self):
        return f"{self.partner.name} - {self.amount} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        # Auto-connect partner to user if not set
        if not self.partner and hasattr(self.created_by, 'partner_profile'):
            self.partner = self.created_by.partner_profile
            
        super().save(*args, **kwargs)

    def mark_as_available(self):
        if self.status == self.Status.PENDING:
            self.status = self.Status.AVAILABLE
            self.save()
            return True
        return False
    
    def mark_as_processing(self, payout=None):
        if self.status == self.Status.AVAILABLE:
            self.status = self.Status.PROCESSING
            if payout:
                self.payout = payout
            self.save()
            return True
        return False
    
    def mark_as_paid(self):
        if self.status == self.Status.PROCESSING:
            self.status = self.Status.PAID
            self.save()
            return True
        return False
        
    def cancel(self, reason=None):
        self.status = self.Status.CANCELLED
        if reason:
            self.notes = f"{self.notes or ''}\nCancellation reason: {reason}"
        self.save()
        return True
    
    def get_related_referral(self):
        if hasattr(self, 'referral'):
            return self.referral
        return None