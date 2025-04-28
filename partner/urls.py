# partner/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PartnerOnboardingLinkViewSet, ProductViewSet, TestimonialViewSet, PartnerProfileViewSet

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product')
router.register(r'testimonials', TestimonialViewSet, basename='testimonial')
router.register(r'partner-profiles', PartnerProfileViewSet, basename='partnerprofile')
router.register(r'onboarding-links', PartnerOnboardingLinkViewSet)

urlpatterns = [
    path('', include(router.urls)),
]

# ---- Available Endpoints ----
# ProductViewSet:
#   GET     /products/
#   POST    /products/
#   GET     /products/{id}/
#   PUT     /products/{id}/
#   PATCH   /products/{id}/
#   DELETE  /products/{id}/
#   GET     /products/stats/

# TestimonialViewSet:
#   GET     /testimonials/
#   POST    /testimonials/
#   GET     /testimonials/{id}/
#   PUT     /testimonials/{id}/
#   PATCH   /testimonials/{id}/
#   DELETE  /testimonials/{id}/
#   POST    /testimonials/{id}/approve/
#   POST    /testimonials/{id}/reject/

# PartnerProfileViewSet:
#   GET     /partner-profiles/
#   POST    /partner-profiles/
#   GET     /partner-profiles/{id}/
#   PUT     /partner-profiles/{id}/
#   PATCH   /partner-profiles/{id}/
#   DELETE  /partner-profiles/{id}/
#   GET     /partner-profiles/dashboard/
#   POST    /partner-profiles/{id}/update_status/
#   POST    /partner-profiles/{id}/add_products/
#   POST    /partner-profiles/{id}/remove_products/
