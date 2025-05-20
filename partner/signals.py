# from django.db.models.signals import post_save, post_delete
# from django.dispatch import receiver

# from referrals_management.models import Referral

# from .models import ProductStats
# from django.db import transaction
# import logging

# logger = logging.getLogger(__name__)

# @receiver(post_save, sender=Referral)
# def update_product_stats_on_referral_change(sender, instance, created, **kwargs):
#     """
#     Update product statistics whenever a referral is created or updated
#     """
#     if instance.product:
#         transaction.on_commit(lambda: update_stats_for_product(instance.product.id))

# @receiver(post_delete, sender=Referral)
# def update_product_stats_on_referral_delete(sender, instance, **kwargs):
#     """
#     Update product statistics whenever a referral is deleted
#     """
#     if instance.product:
#         transaction.on_commit(lambda: update_stats_for_product(instance.product.id))

# def update_stats_for_product(product_id):
#     """
#     Wrapper function to handle errors and retry logic
#     """
#     try:
#         ProductStats.update_stats_for_product(product_id)
#     except Exception as e:
#         logger.error(f"Error updating stats for product {product_id}: {str(e)}")
#         # You could implement retry logic here if needed