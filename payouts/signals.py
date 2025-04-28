# payouts/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from payouts.models import Payout

@receiver(post_save, sender=Payout)
def handle_payout_processing(sender, instance, created, **kwargs):
    if created:
        # In a real app, this would be done in a transaction
        instance.partner.earnings.filter(status='available').update(status='processing')
    
    if instance.status == Payout.Status.COMPLETED:
        instance.partner.earnings.filter(status='processing').update(status='paid')