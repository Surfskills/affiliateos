from django.contrib import admin
from .models import Resource, ResourceCategory, ResourceTag, ResourceVersion

class ResourceVersionInline(admin.TabularInline):
    model = ResourceVersion
    extra = 0
    readonly_fields = ['created_at', 'created_by']
    
    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

class ResourceAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'resource_type', 'visibility', 'download_count', 'view_count', 'update_date']
    list_filter = ['category', 'resource_type', 'visibility']
    search_fields = ['title', 'description']
    filter_horizontal = ['tags', 'partners']
    inlines = [ResourceVersionInline]
    readonly_fields = ['upload_date', 'update_date', 'download_count', 'view_count', 'uploaded_by']
    
    def save_model(self, request, obj, form, change):
        if not obj.uploaded_by:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)

admin.site.register(Resource, ResourceAdmin)
admin.site.register(ResourceCategory)
admin.site.register(ResourceTag)
admin.site.register(ResourceVersion)