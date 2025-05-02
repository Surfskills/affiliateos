# payouts/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from payouts.models import Payout
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.db import transaction
from .models import Payout, Earnings
import logging
from django.utils import timezone


logger = logging.getLogger(__name__)
@receiver(post_save, sender=Payout)
def handle_payout_processing(sender, instance, created, **kwargs):
    if created:
        # In a real app, this would be done in a transaction
        instance.partner.earnings.filter(status='available').update(status='processing')
    
    if instance.status == Payout.Status.COMPLETED:
        instance.partner.earnings.filter(status='processing').update(status='paid')



@receiver(pre_save, sender=Payout)
def update_earnings_on_payout_completion(sender, instance, **kwargs):
    """
    Update associated earnings when a payout is marked as completed
    """
    if not instance.pk:
        return  # New instance being created
    
    try:
        old_instance = Payout.objects.get(pk=instance.pk)
        
        # Check if status changed to COMPLETED
        if (old_instance.status != Payout.Status.COMPLETED and 
            instance.status == Payout.Status.COMPLETED):
            
            logger.info(f"Payout {instance.id} marked as completed - updating earnings")
            
            with transaction.atomic():
                # 1. Update earnings directly linked to this payout
                direct_updated = Earnings.objects.filter(
                    payout=instance,
                    status__in=[Earnings.Status.AVAILABLE, Earnings.Status.PROCESSING]
                ).update(
                    status=Earnings.Status.PAID,
                    paid_date=timezone.now()
                )
                
                # 2. Find and update any available earnings for this partner that aren't linked yet
                unlinked_updated = Earnings.objects.filter(
                    partner=instance.partner,
                    status=Earnings.Status.AVAILABLE,
                    payout__isnull=True
                ).update(
                    status=Earnings.Status.PAID,
                    payout=instance,
                    paid_date=timezone.now()
                )
                
                logger.info(
                    f"Updated {direct_updated + unlinked_updated} earnings to PAID status "
                    f"(direct: {direct_updated}, unlinked: {unlinked_updated})"
                )
                
    except Payout.DoesNotExist:
        pass  # Instance being created
    except Exception as e:
        logger.error(f"Error updating earnings for payout {instance.id}: {str(e)}")
        raise  # Re-raise to prevent save if there's an error