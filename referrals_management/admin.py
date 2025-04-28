from django.contrib import admin
from .models import Referral, ReferralTimeline


@admin.register(ReferralTimeline)
class ReferralTimelineAdmin(admin.ModelAdmin):
    list_display = ('referral', 'status', 'timestamp', 'created_by')
    list_filter = ('status', 'timestamp')
    search_fields = ('referral__client_name', 'note', 'created_by__email')
    ordering = ('-timestamp',)
    readonly_fields = ('referral', 'status', 'timestamp', 'note', 'created_by')


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = (
        'client_name', 'client_email', 'partner', 'product',
        'status', 'date_submitted', 'expected_implementation_date',
        'potential_commission', 'actual_commission'
    )
    list_filter = ('status', 'product', 'date_submitted', 'partner')
    search_fields = (
        'client_name', 'client_email', 'client_phone', 'company',
        'referral_code', 'partner__user__email'
    )
    autocomplete_fields = ('partner', 'product', 'user', 'updated_by')
    ordering = ('-date_submitted',)
    readonly_fields = ('referral_code', 'actual_commission', 'date_submitted', 'updated_at')
    fieldsets = (
        (None, {
            'fields': (
                'user', 'partner', 'referral_code', 'client_name', 'client_email', 'client_phone',
                'company', 'product', 'status', 'prev_status'
            )
        }),
        ('Commission Details', {
            'fields': ('potential_commission', 'actual_commission')
        }),
        ('Timeline Info', {
            'fields': ('timeline', 'expected_implementation_date') 
        }),
        ('Additional Info', {
            'fields': ('budget_range', 'notes', 'updated_by', 'updated_at')
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('partner', 'product', 'user')
