from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Create a router for our API viewsets
router = DefaultRouter()
router.register(r'documents', views.DocumentViewSet, basename='document')
router.register(r'requirements', views.DocumentRequirementViewSet, basename='documentrequirement')

# URL patterns for the documents app
urlpatterns = [
    # API endpoints
    path('', include(router.urls)),
    
    # Direct browser views
    path('upload/', views.document_upload_view, name='document-upload'),
    path('view/<int:pk>/', views.document_view, name='document-view'),
    path('download/<int:pk>/', views.document_download_view, name='document-download'),
]