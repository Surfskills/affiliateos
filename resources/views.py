from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from django.conf import settings
from .models import Resource, ResourceCategory, ResourceTag
from .serializers import (
    ResourceSerializer, ResourceCategorySerializer, 
    ResourceTagSerializer, ResourceUploadSerializer
)
from django.http import FileResponse
from django.shortcuts import get_object_or_404

class ResourceCategoryViewSet(viewsets.ModelViewSet):
    queryset = ResourceCategory.objects.all()
    serializer_class = ResourceCategorySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'slug'

class ResourceTagViewSet(viewsets.ModelViewSet):
    queryset = ResourceTag.objects.all()
    serializer_class = ResourceTagSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'slug'


class ResourceViewSet(viewsets.ModelViewSet):
    serializer_class = ResourceSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        queryset = Resource.objects.all()
        
        # Filter based on visibility and user permissions
        user = self.request.user
        if not user.is_authenticated:
            queryset = queryset.filter(visibility='public')
        elif not user.is_staff:
            queryset = queryset.filter(
                Q(visibility='public') | 
                Q(visibility='partner', partners=user) |
                Q(uploaded_by=user)
            ).distinct()
        
        # Apply filters
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category__slug=category)
        
        resource_type = self.request.query_params.get('type')
        if resource_type:
            queryset = queryset.filter(resource_type=resource_type)
        
        visibility = self.request.query_params.get('visibility')
        if visibility and user.is_staff:
            queryset = queryset.filter(visibility=visibility)
        
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | 
                Q(description__icontains=search)
            )
        
        tags = self.request.query_params.getlist('tags')
        if tags:
            queryset = queryset.filter(tags__slug__in=tags).distinct()
        
        # Filter by creator (uploaded_by)
        # FIXED: Use the uploaded_by email directly instead of trying to access username
        uploaded_by = self.request.query_params.get('uploaded_by')
        if uploaded_by:
            queryset = queryset.filter(uploaded_by__email=uploaded_by)
        
        return queryset.select_related('category', 'uploaded_by').prefetch_related('tags', 'partners', 'versions')
    
    def get_serializer_class(self):
        if self.action == 'create':
            return ResourceUploadSerializer
        return super().get_serializer_class()
    
    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)
    
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        resource = self.get_object()
        resource.download_count += 1
        resource.save()
        
        file_handle = resource.file.open()
        response = FileResponse(file_handle, content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{resource.file.name}"'
        return response
    
    @action(detail=True, methods=['post'])
    def increment_view(self, request, pk=None):
        resource = self.get_object()
        resource.view_count += 1
        resource.save()
        return Response({'status': 'view count incremented'})