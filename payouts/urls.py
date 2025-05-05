# payouts/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from payouts.views import EarningsViewSet, PayoutSettingViewSet, PayoutViewSet

router = DefaultRouter()
router.register(r'payouts', PayoutViewSet, basename='payout')
router.register(r'payout-settings', PayoutSettingViewSet)
router.register(r'earnings', EarningsViewSet)

urlpatterns = [
    path('', include(router.urls)),
    # Add custom action URLs that match your frontend API calls
    path('payouts/<str:id>/process/', PayoutViewSet.as_view({'post': 'process'}), name='payout-process'),
    path('payouts/<str:id>/complete/', PayoutViewSet.as_view({'post': 'complete'}), name='payout-complete'),
    path('payouts/<str:id>/fail/', PayoutViewSet.as_view({'post': 'fail'}), name='payout-fail'),
    path('payouts/<str:id>/cancel/', PayoutViewSet.as_view({'post': 'cancel'}), name='payout-cancel'),
    
    # Custom actions for PayoutSettingViewSet
    path('payout-settings/schedules/', PayoutSettingViewSet.as_view({'get': 'schedules'}), name='payout-settings-schedules'),
    path('payout-settings/payment-methods/', PayoutSettingViewSet.as_view({'get': 'payment_methods'}), name='payout-settings-payment-methods'),
    path('payout-settings/mine/', PayoutSettingViewSet.as_view({'get': 'mine', 'patch': 'mine'}), name='payout-settings-mine'),
    path('payout-settings/add-payment-method/', PayoutSettingViewSet.as_view({'post': 'add_payment_method'}), name='payout-settings-add-payment-method'),
]
