# referrals/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver

from referrals_management.models import Referral


@receiver(post_save, sender=Referral)
def handle_referral_conversion(sender, instance, created, **kwargs):
    if instance.status == Referral.Status.CONVERTED:
        instance.create_earning()