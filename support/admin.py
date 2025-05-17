from django.contrib import admin
from .models import SupportTicket, Comment, SupportTicketAttachment

class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    readonly_fields = ['author', 'created_at']

class AttachmentInline(admin.TabularInline):
    model = SupportTicketAttachment
    extra = 0

@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ('subject', 'submitted_by', 'status', 'priority', 'created_at')
    list_filter = ('status', 'priority', 'issue_category')
    search_fields = ('subject', 'description', 'affiliate_id')
    inlines = [CommentInline, AttachmentInline]
    readonly_fields = ('submitted_by', 'created_at', 'updated_at')
    fieldsets = (
        (None, {'fields': ('submitted_by', 'affiliate_id', 'status', 'priority')}),
        ('Ticket Details', {'fields': (
            'subject', 'description', 'issue_category', 
            'payment_related', 'marketing_materials',
            'commission_dispute', 'technical_issue',
            'affected_customers'
        )}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'author', 'created_at')
    search_fields = ('content', 'author__email')

@admin.register(SupportTicketAttachment)
class SupportTicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'file', 'uploaded_at')
    search_fields = ('ticket__subject',)