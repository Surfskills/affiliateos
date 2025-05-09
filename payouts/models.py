from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from decimal import Decimal
from partner.models import PartnerProfile
from referrals_management.models import Referral
import uuid
import re
from django.db.models import Sum
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
import logging

logger = logging.getLogger(__name__)

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
        """Mark payout as completed and update all related earnings to paid status"""
        from .models import Earnings  # Local import to avoid circular imports
        
        # Update payout status
        self.status = self.Status.COMPLETED
        self.processed_date = timezone.now()
        self.transaction_id = transaction_id
        self.processed_by = user if user else self.processed_by
        self.save()
        
        # Update all earnings associated with this payout
        try:
            with transaction.atomic():
                # 1. Direct earnings linked to this payout
                direct_earnings = Earnings.objects.filter(
                    payout=self,
                    status__in=[Earnings.Status.AVAILABLE, Earnings.Status.PROCESSING]
                )
                
                update_count = 0
                for earning in direct_earnings:
                    earning.status = Earnings.Status.PAID
                    earning.paid_date = timezone.now()
                    earning.save(update_fields=['status', 'paid_date'])
                    update_count += 1
                
                # 2. Find and update any available earnings for this partner that aren't linked yet
                available_earnings = Earnings.objects.filter(
                    partner=self.partner,
                    status=Earnings.Status.AVAILABLE,
                    payout__isnull=True
                )
                
                for earning in available_earnings:
                    earning.status = Earnings.Status.PAID
                    earning.payout = self
                    earning.paid_date = timezone.now()
                    earning.save(update_fields=['status', 'payout', 'paid_date'])
                    update_count += 1
                
                # 3. Update earnings linked via referrals
                for payout_ref in self.referrals.all():
                    if hasattr(payout_ref, 'referral') and hasattr(payout_ref.referral, 'earning'):
                        earning = payout_ref.referral.earning
                        if earning.status in [Earnings.Status.AVAILABLE, Earnings.Status.PROCESSING]:
                            earning.status = Earnings.Status.PAID
                            earning.payout = self
                            earning.paid_date = timezone.now()
                            earning.save(update_fields=['status', 'payout', 'paid_date'])
                            update_count += 1
                
                logger.info(f"Payout {self.id} completed: Updated {update_count} earnings to PAID status")
        
        except Exception as e:
            logger.error(f"Error updating earnings for payout {self.id}: {str(e)}")
            # We don't raise the exception here to allow the payout to complete
            # even if there are issues with updating some earnings
        
        return self
    def _update_associated_earnings(self):
        """Update all earnings associated with this payout to PAID status"""
        try:
            with transaction.atomic():
                # Update earnings directly linked to this payout
                updated_direct = 0
                for earning in self.earnings_included.filter(
                    status__in=['processing', 'available']
                ):
                    earning.status = 'paid'
                    earning.paid_date = timezone.now()
                    earning.save(update_fields=['status', 'paid_date'])
                    updated_direct += 1
                
                # Update earnings linked through referrals
                updated_referrals = 0
                for payout_ref in self.referrals.select_related('referral__earning').all():
                    if hasattr(payout_ref.referral, 'earning'):
                        earning = payout_ref.referral.earning
                        if earning.status in ['processing', 'available']:
                            earning.status = 'paid'
                            earning.payout = self
                            earning.paid_date = timezone.now()
                            earning.save(update_fields=['status', 'payout', 'paid_date'])
                            updated_referrals += 1
                
                logger.info(
                    f"Payout {self.id} completed: Updated {updated_direct} direct earnings and {updated_referrals} referral earnings to PAID"
                )
                
                # Double-check for any missed earnings related to this payout
                # This will find any earnings related to the payout that weren't caught by the direct linkage checks
                from .models import Earnings  # Local import to avoid circular references
                
                # Look for available/processing earnings that should be paid
                missed_earnings = Earnings.objects.filter(
                    Q(payout=self) | Q(referral__payout_referrals__payout=self),
                    status__in=['processing', 'available']
                ).distinct()
                
                if missed_earnings.exists():
                    logger.info(f"Found {missed_earnings.count()} additional earnings to update for payout {self.id}")
                    for earning in missed_earnings:
                        earning.status = 'paid'
                        earning.paid_date = timezone.now()
                        earning.save(update_fields=['status', 'paid_date'])
                    
        except Exception as e:
            logger.error(f"Error updating earnings for payout {self.id}: {str(e)}")
            # You can choose to re-raise the exception for critical errors
            # raise
    
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
    def debug_payout_earnings(payout_id):
        """
        Utility function to debug the relationship between a payout and its earnings.
        This helps identify why earnings aren't being updated correctly.
        """
        from django.db import connection
        from payouts.models import Payout, Earnings
        
        try:
            payout = Payout.objects.get(id=payout_id)
        except Payout.DoesNotExist:
            print(f"Payout with ID {payout_id} does not exist")
            return
        
        print(f"Payout {payout_id} details:")
        print(f"Status: {payout.status}")
        print(f"Partner: {payout.partner.name}")
        print(f"Amount: {payout.amount}")
        
        # 1. Check direct earnings
        direct_earnings = Earnings.objects.filter(payout=payout)
        print(f"\nDirect earnings count: {direct_earnings.count()}")
        
        status_counts = {}
        for earning in direct_earnings:
            status = earning.status
            status_counts[status] = status_counts.get(status, 0) + 1
        
        print("Status distribution:")
        for status, count in status_counts.items():
            print(f"  {status}: {count}")
        
        # 2. Check available earnings for this partner
        available_earnings = Earnings.objects.filter(
            partner=payout.partner,
            status='available'
        )
        print(f"\nAvailable earnings for partner {payout.partner.name}: {available_earnings.count()}")
        
        # 3. Check if there are any SQL errors when updating earnings
        print("\nTesting SQL update for available earnings:")
        try:
            with connection.cursor() as cursor:
                # This SQL query should mirror what we're trying to do in the code
                cursor.execute("""
                    UPDATE payouts_earnings
                    SET status = 'paid', paid_date = %s
                    WHERE partner_id = %s AND status = 'available'
                    RETURNING id
                """, [timezone.now(), payout.partner.id])
                updated_ids = cursor.fetchall()
                print(f"Successfully updated {len(updated_ids)} earnings via SQL")
        except Exception as e:
            print(f"SQL error: {str(e)}")
        
        # 4. Check if earnings status values match model definitions
        print("\nChecking earnings status values:")
        status_values = Earnings.objects.values_list('status', flat=True).distinct()
        print(f"Actual status values in database: {list(status_values)}")
        print(f"Status choices in model: {[choice[0] for choice in Earnings.Status.choices]}")
        
        return {
            'payout': payout,
            'direct_earnings': direct_earnings,
            'available_earnings': available_earnings,
            'status_counts': status_counts
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
    # Constants
    DEFAULT_PAYMENT_METHOD = 'bank'
    DEFAULT_PAYOUT_SCHEDULE = 'monthly'
    DEFAULT_MINIMUM_PAYOUT = Decimal('50.00')
    PAYOUT_SCHEDULE_CHOICES = [
        ('manual', _('Manual')),
        ('weekly', _('Weekly')),
        ('biweekly', _('Bi-Weekly')),
        ('monthly', _('Monthly')),
        ('quarterly', _('Quarterly'))
    ]
    
    # Foreign Key to PartnerProfile
    partner = models.OneToOneField(
        PartnerProfile,
        on_delete=models.CASCADE,
        related_name='payout_setting'
    )
    
    # Payment Method Choices
    payment_method = models.CharField(
        max_length=10,
        choices=Payout.PaymentMethod.choices,  # Assuming `Payout.PaymentMethod.choices` exists
        default=DEFAULT_PAYMENT_METHOD
    )
    
    # Payment Details
    payment_details = models.JSONField(default=dict)
    
    # Minimum Payout Amount
    minimum_payout_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('50.00')
    )
    
    # Auto Payout Flag
    auto_payout = models.BooleanField(default=False)
    
    # Payout Schedule
    payout_schedule = models.CharField(
        max_length=20,
        choices=PAYOUT_SCHEDULE_CHOICES,
        default='monthly'
    )
    
    # Last Updated Time
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
        # Normalize keys to snake_case
        if self.payment_details:
            def camel_to_snake(s): 
                return re.sub(r'(?<!^)(?=[A-Z])', '_', s).lower()
            
            self.payment_details = {
                camel_to_snake(k): v for k, v in self.payment_details.items()
            }
        
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
        elif self.payment_method == 'crypto':
            if not self.payment_details.get('wallet_address'):
                raise ValidationError("Cryptocurrency requires a wallet address in payment_details.")
        
        super().clean()



class Earnings(models.Model):
    class Source(models.TextChoices):
        REFERRAL = 'referral', _('Referral')
        BONUS = 'bonus', _('Bonus')
        PROMOTION = 'promotion', _('Promotion')
        OTHER = 'other', _('Other')

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        PENDING_APPROVAL = 'pending_approval', _('Pending Approval')
        AVAILABLE = 'available', _('Available')
        PROCESSING = 'processing', _('Processing')
        PAID = 'paid', _('Paid')
        CANCELLED = 'cancelled', _('Cancelled')
        REJECTED = 'rejected', _('Rejected')

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
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    paid_date = models.DateTimeField(null=True, blank=True, help_text="When these earnings were paid out")
    date = models.DateField()
    approval_date = models.DateTimeField(null=True, blank=True)
    rejection_date = models.DateTimeField(null=True, blank=True)
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

    def save(self, *args, **kwargs):
        """
        Override save to enforce business rules on status transitions
        and handle partner assignment
        """
        # Assign partner from created_by if not already set
        if not self.partner and hasattr(self.created_by, 'partner_profile'):
            self.partner = self.created_by.partner_profile
        
        # If this is a new record (no ID yet) and it's a referral,
        # ensure it starts in PENDING_APPROVAL
        if not self.id and self.source == self.Source.REFERRAL:
            self.status = self.Status.PENDING_APPROVAL
            
        super().save(*args, **kwargs)

    def mark_as_available(self):
        """
        Move earnings to AVAILABLE status, enforcing approval workflow
        for referral-based earnings
        """
        # For referral earnings, they must go through approval first
        if self.source == self.Source.REFERRAL:
            if self.status == self.Status.PENDING:
                self.status = self.Status.PENDING_APPROVAL
                self.save()
                return False  # Not available yet, needs approval
            elif self.status == self.Status.PENDING_APPROVAL:
                return False  # Not available yet, needs approval
            
        # For non-referral earnings or already approved referrals
        if self.status in [self.Status.PENDING, self.Status.PENDING_APPROVAL]:
            self.status = self.Status.AVAILABLE
            self.save()
            return True
        return False

    def mark_as_processing(self, payout=None):
        """Mark earnings as processing for payout"""
        if self.status == self.Status.AVAILABLE:
            self.status = self.Status.PROCESSING
            if payout:
                self.payout = payout
            self.save()
            return True
        return False

    def mark_as_paid(self):
        """Mark earnings as paid after processing"""
        if self.status in [self.Status.PROCESSING, self.Status.AVAILABLE]:
            self.status = self.Status.PAID
            self.save()
            return True
        return False

    def approve(self, approved_by=None):
        """Admin approves pending earnings to make them available"""
        if self.status != self.Status.PENDING_APPROVAL:
            return False
        
        self.status = self.Status.AVAILABLE
        self.approved_by = approved_by
        self.approval_date = timezone.now()
        self.save()
        return True

    def reject(self, rejected_by=None, reason=None):
        """Admin rejects pending earnings"""
        if self.status != self.Status.PENDING_APPROVAL:
            return False
        
        self.status = self.Status.REJECTED
        if reason:
            self.notes = f"{self.notes or ''}\nRejection reason: {reason}"
        self.rejected_by = rejected_by
        self.rejection_date = timezone.now()
        self.save()
        return True

    def cancel(self, reason=None):
        """Cancel earnings"""
        # Can only cancel if not already paid
        if self.status not in [self.Status.PAID, self.Status.CANCELLED]:
            self.status = self.Status.CANCELLED
            if reason:
                self.notes = f"{self.notes or ''}\nCancellation reason: {reason}"
            self.save()
            return True
        return False

    def get_related_referral(self):
        """Get the associated referral if it exists"""
        if hasattr(self, 'referral'):
            return self.referral
        return None
        
    def __str__(self):
        return f"{self.partner.name} - {self.amount} ({self.get_status_display()})"
