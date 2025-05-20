from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PartnerOnboardingLinkViewSet, 
    PartnerViewSet, 
    ProductViewSet, 
    TestimonialViewSet,
    DashboardViewSet
)

router = DefaultRouter()
router.register(r'partner-profiles', PartnerViewSet, basename='partnerprofile')
router.register(r'onboarding-links', PartnerOnboardingLinkViewSet, basename='onboardinglink')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'testimonials', TestimonialViewSet, basename='testimonial')
router.register(r'dashboard', DashboardViewSet, basename='dashboard')

urlpatterns = [
    path('', include(router.urls)),
]