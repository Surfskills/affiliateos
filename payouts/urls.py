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
]