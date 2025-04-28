# payouts/models.py
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from decimal import Decimal
from partner.models import PartnerProfile
from referrals_management.models import Referral
import uuid

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
    partner = models.ForeignKey(PartnerProfile, on_delete=models.CASCADE, related_name='payouts')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING, db_index=True)
    request_date = models.DateTimeField(auto_now_add=True)
    processed_date = models.DateTimeField(null=True, blank=True)
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices)
    payment_details = models.JSONField(default=dict)
    transaction_id = models.CharField(max_length=100, null=True, blank=True)
    note = models.TextField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Track who processed the payout
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_payouts'
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
        if not self.id:
            self.id = f"PY-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

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
        
        # Update associated earnings
        for payout_referral in self.referrals.all():
            if hasattr(payout_referral.referral, 'earning'):
                earning = payout_referral.referral.earning
                earning.status = 'paid'
                earning.save()
        
        return self

    def fail(self, error_message, user=None):
        self.status = self.Status.FAILED
        self.note = f"{self.note or ''}\nError: {error_message}"
        self.processed_by = user if user else self.processed_by
        self.save()
        return self
        
    def cancel(self, reason=None, user=None):
        self.status = self.Status.CANCELLED
        if reason:
            self.note = f"{self.note or ''}\nCancellation reason: {reason}"
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
    partner = models.OneToOneField(PartnerProfile, on_delete=models.CASCADE, related_name='payout_setting')
    payment_method = models.CharField(max_length=10, choices=Payout.PaymentMethod.choices, default=Payout.PaymentMethod.BANK)
    payment_details = models.JSONField(default=dict)
    minimum_payout_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('50.00'))
    auto_payout = models.BooleanField(default=False)
    payout_schedule = models.CharField(max_length=20, choices=[
        ('manual', _('Manual')),
        ('weekly', _('Weekly')),
        ('biweekly', _('Bi-weekly')),
        ('monthly', _('Monthly')),
        ('quarterly', _('Quarterly'))
    ], default='monthly')
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

    partner = models.ForeignKey(PartnerProfile, on_delete=models.CASCADE, related_name='earnings')
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
    
    # Track when earnings were included in a payout
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
