# urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'support/tickets', views.SupportTicketViewSet)
router.register(r'support/comments', views.CommentViewSet)

urlpatterns = [
    path('', include(router.urls)),
]