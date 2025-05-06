"""
URL configuration for fred project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/

Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # Django Admin
    path('admin/', admin.site.urls),

    # Authentication endpoints (login, register, etc.)
    path('api/auth/', include('authentication.urls')),

    # Partner module: products, testimonials, partner profiles
    path('api/partner/', include('partner.urls')),

    # Referral management: referral creation, tracking
    path('api/referrals/', include('referrals_management.urls')),

    # Payouts module: earnings, withdrawals
    path('api/payouts/', include('payouts.urls')),

    path('api/', include('documents_management.urls')),
]
