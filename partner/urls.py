from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PartnerOnboardingLinkViewSet, PartnerViewSet, ProductViewSet, TestimonialViewSet

router = DefaultRouter()
router.register(r'partner-profiles', PartnerViewSet, basename='partner')
router.register(r'onboarding-links', PartnerOnboardingLinkViewSet)
router.register(r'products', ProductViewSet)
router.register(r'testimonials', TestimonialViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
