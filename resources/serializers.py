from rest_framework import serializers

from authentication.models import User
from .models import Resource, ResourceCategory, ResourceTag, ResourceVersion


class ResourceTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResourceTag
        fields = ['id', 'name', 'slug']

class ResourceCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ResourceCategory
        fields = ['id', 'name', 'slug']

class ResourceVersionSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField()
    
    class Meta:
        model = ResourceVersion
        fields = ['id', 'version', 'notes', 'file', 'created_at', 'created_by']
        read_only_fields = ['created_at']

class ResourceSerializer(serializers.ModelSerializer):
    category = ResourceCategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=ResourceCategory.objects.all(),
        source='category',
        write_only=True
    )
    tags = ResourceTagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(
        queryset=ResourceTag.objects.all(),
        many=True,
        source='tags',
        write_only=True,
        required=False
    )
    partners = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        many=True,
        required=False
    )
    uploaded_by = serializers.StringRelatedField(read_only=True)
    versions = ResourceVersionSerializer(many=True, read_only=True)
    thumbnail_url = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    file_size_display = serializers.SerializerMethodField()
    
    class Meta:
        model = Resource
        fields = [
            'id', 'title', 'description', 'category', 'category_id', 
            'tags', 'tag_ids', 'visibility', 'resource_type', 
            'thumbnail', 'thumbnail_url', 'file', 'file_url', 
            'file_size', 'file_size_display', 'partners', 
            'upload_date', 'update_date', 'download_count', 
            'view_count', 'uploaded_by', 'versions'
        ]
        read_only_fields = [
            'upload_date', 'update_date', 'download_count', 
            'view_count', 'uploaded_by', 'thumbnail_url', 
            'file_url', 'file_size_display'
        ]
    
    def get_thumbnail_url(self, obj):
        if obj.thumbnail:
            return obj.thumbnail.url
        return None
    
    def get_file_url(self, obj):
        if obj.file:
            return obj.file.url
        return None
    
    def get_file_size_display(self, obj):
        if obj.file_size < 1024:
            return f"{obj.file_size} B"
        elif obj.file_size < 1024 * 1024:
            return f"{obj.file_size / 1024:.1f} KB"
        else:
            return f"{obj.file_size / (1024 * 1024):.1f} MB"
    
    def create(self, validated_data):
        validated_data['uploaded_by'] = self.context['request'].user
        return super().create(validated_data)

class ResourceUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Resource
        fields = [
            'title', 'description', 'category', 'tags', 
            'visibility', 'resource_type', 'thumbnail', 'file', 'partners'
        ]