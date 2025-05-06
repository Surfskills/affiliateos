from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.models import ContentType
from .models import Document, DocumentRequirement

@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    """Admin configuration for Document model."""
    list_display = [
        'name', 
        'user_link', 
        'document_type', 
        'status_badge', 
        'file_link',
        'created_at', 
        'updated_at', 
        'verification_date'
    ]
    list_filter = ['status', 'document_type', 'created_at', 'updated_at', 'verification_date']
    search_fields = ['name', 'description', 'file_name', 'user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at', 'file_size', 'file_preview']
    fieldsets = (
        (None, {
            'fields': ('user', 'name', 'description')
        }),
        (_('Document Details'), {
            'fields': ('document_type', 'status', 'file', 'file_name', 'content_type', 'file_size', 'file_preview')
        }),
        (_('Verification'), {
            'fields': ('verification_date', 'verified_by', 'verification_notes')
        }),
        (_('Metadata'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    actions = ['mark_as_verified', 'mark_as_pending', 'mark_as_missing']
    
    def user_link(self, obj):
        """Return a link to the user admin page."""
        if obj.user:
            user = obj.user
            ct = ContentType.objects.get_for_model(user.__class__)
            try:
                url = reverse(f'admin:{ct.app_label}_{ct.model}_change', args=[user.pk])
                return format_html('<a href="{}">{}</a>', url, user)
            except Exception:
                return str(user)
        return '-'
    user_link.short_description = _('User')
    user_link.admin_order_field = 'user__username'
    
    def file_link(self, obj):
        """Return a link to download the file if it exists."""
        if obj.file:
            return format_html('<a href="{}" target="_blank">{}</a>', obj.file.url, obj.file_name or obj.file.name)
        return '-'
    file_link.short_description = _('File')
    
    def file_preview(self, obj):
        """Return a preview of the file if it's an image, or a download link otherwise."""
        if not obj.file:
            return '-'
        
        file_url = obj.file.url
        
        # Check if it's an image
        if obj.content_type and obj.content_type.startswith('image/'):
            return format_html(
                '<a href="{0}" target="_blank"><img src="{0}" alt="{1}" style="max-height: 200px; max-width: 100%;" /></a>',
                file_url,
                obj.file_name or obj.file.name
            )
        
        # For PDFs, provide a download link
        if obj.content_type == 'application/pdf':
            return format_html(
                '<a href="{0}" target="_blank" class="button">View PDF</a>',
                file_url
            )
            
        # For other files, just provide a download link
        return format_html(
            '<a href="{0}" target="_blank" class="button">Download File</a>',
            file_url
        )
    file_preview.short_description = _('File Preview')
    
    def status_badge(self, obj):
        """Return a colored badge for the status."""
        colors = {
            'verified': 'green',
            'pending': 'orange',
            'missing': 'red',
            'required': 'gray'
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 10px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'
    
    def mark_as_verified(self, request, queryset):
        """Mark selected documents as verified."""
        updated = queryset.update(
            status='verified',
            verification_date=admin.models.timezone.now(),
            verified_by=request.user
        )
        self.message_user(request, _(f"{updated} documents marked as verified."))
    mark_as_verified.short_description = _("Mark selected documents as verified")
    
    def mark_as_pending(self, request, queryset):
        """Mark selected documents as pending."""
        updated = queryset.update(status='pending')
        self.message_user(request, _(f"{updated} documents marked as pending."))
    mark_as_pending.short_description = _("Mark selected documents as pending")
    
    def mark_as_missing(self, request, queryset):
        """Mark selected documents as missing."""
        updated = queryset.update(status='missing')
        self.message_user(request, _(f"{updated} documents marked as missing."))
    mark_as_missing.short_description = _("Mark selected documents as missing")


@admin.register(DocumentRequirement)
class DocumentRequirementAdmin(admin.ModelAdmin):
    """Admin configuration for DocumentRequirement model."""
    list_display = ['name', 'document_type', 'is_required', 'max_file_size_mb', 'allowed_extensions', 'active']
    list_filter = ['document_type', 'is_required', 'active']
    search_fields = ['name', 'description']
    list_editable = ['is_required', 'active']
    
    def max_file_size_mb(self, obj):
        """Display max file size in MB."""
        if obj.max_file_size:
            return f"{obj.max_file_size / (1024 * 1024):.1f} MB"
        return '-'
    max_file_size_mb.short_description = _('Max Size')