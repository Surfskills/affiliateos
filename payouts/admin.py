from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.db.models import Sum
from .models import Payout, PayoutReferral, PayoutSetting, Earnings


class PayoutReferralInline(admin.TabularInline):
    model = PayoutReferral
    extra = 0
    readonly_fields = ('referral', 'amount', 'created_at')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'partner_display',
        'amount',
        'status_display',
        'payment_method_display',
        'request_date',
        'processed_date',
        'processed_by_display'
    )
    list_display_links = ('id', 'partner_display')
    list_filter = ('status', 'payment_method', 'request_date', 'processed_date')
    search_fields = ('id', 'partner__user__email', 'partner__user__first_name', 'partner__user__last_name', 'transaction_id')
    readonly_fields = ('id', 'request_date', 'updated_at', 'processed_by_display', 'total_referrals', 'total_amount')
    inlines = [PayoutReferralInline]
    actions = ['mark_as_processing', 'mark_as_completed', 'mark_as_failed']
    list_select_related = ('partner', 'processed_by')

    fieldsets = (
        (None, {
            'fields': ('id', 'partner', 'amount', 'status', 'payment_method', 'payment_details')
        }),
        (_('Timing Information'), {
            'fields': ('request_date', 'processed_date', 'updated_at'),
            'classes': ('collapse',)
        }),
        (_('Processing Information'), {
            'fields': ('transaction_id', 'processed_by_display', 'note')
        }),
        (_('Referrals Summary'), {
            'fields': ('total_referrals', 'total_amount'),
            'classes': ('collapse',)
        }),
    )

    def partner_display(self, obj):
        return obj.partner.name
    partner_display.short_description = _('Partner')
    partner_display.admin_order_field = 'partner__name'

    def status_display(self, obj):
        return obj.get_status_display()
    status_display.short_description = _('Status')
    status_display.admin_order_field = 'status'

    def payment_method_display(self, obj):
        return obj.get_payment_method_display()
    payment_method_display.short_description = _('Payment Method')
    payment_method_display.admin_order_field = 'payment_method'

    def processed_by_display(self, obj):
        return obj.processed_by.get_full_name() if obj.processed_by else None
    processed_by_display.short_description = _('Processed By')

    def total_referrals(self, obj):
        return obj.referrals.count()
    total_referrals.short_description = _('Total Referrals')

    def total_amount(self, obj):
        total = obj.referrals.aggregate(Sum('amount'))['amount__sum'] or 0
        return f"${total:,.2f}"
    total_amount.short_description = _('Total Referrals Amount')

    def mark_as_processing(self, request, queryset):
        count = 0
        for payout in queryset.filter(status=Payout.Status.PENDING):
            payout.process(request.user)
            count += 1
        self.message_user(request, _(f"{count} payout(s) marked as processing."))
    mark_as_processing.short_description = _("Mark selected payouts as processing")

    def mark_as_completed(self, request, queryset):
        count = 0
        for payout in queryset.filter(status=Payout.Status.PROCESSING):
            payout.complete(user=request.user)
            count += 1
        self.message_user(request, _(f"{count} payout(s) marked as completed."))
    mark_as_completed.short_description = _("Mark selected payouts as completed")

    def mark_as_failed(self, request, queryset):
        count = 0
        for payout in queryset.exclude(status=Payout.Status.COMPLETED):
            payout.fail("Admin action", user=request.user)
            count += 1
        self.message_user(request, _(f"{count} payout(s) marked as failed."))
    mark_as_failed.short_description = _("Mark selected payouts as failed")


@admin.register(PayoutReferral)
class PayoutReferralAdmin(admin.ModelAdmin):
    list_display = ('payout_id', 'referral_display', 'amount', 'created_at')
    list_filter = ('payout__status', 'created_at')
    search_fields = ('payout__id', 'referral__client_name', 'referral__client_email')
    readonly_fields = ('payout', 'referral', 'amount', 'created_at')
    list_select_related = ('payout', 'referral')

    def payout_id(self, obj):
        return obj.payout.id
    payout_id.short_description = _('Payout ID')
    payout_id.admin_order_field = 'payout__id'

    def referral_display(self, obj):
        return f"{obj.referral.client_name} ({obj.referral.client_email})"
    referral_display.short_description = _('Referral')
    referral_display.admin_order_field = 'referral__client_name'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PayoutSetting)
class PayoutSettingAdmin(admin.ModelAdmin):
    list_display = (
        'partner_display',
        'payment_method_display',
        'minimum_payout_amount',
        'auto_payout',
        'schedule_display',
        'updated_at'
    )
    list_filter = ('payment_method', 'auto_payout', 'payout_schedule')
    search_fields = ('partner__user__email', 'partner__user__first_name', 'partner__user__last_name')
    readonly_fields = ('updated_at',)
    list_select_related = ('partner',)

    def partner_display(self, obj):
        return obj.partner.name
    partner_display.short_description = _('Partner')
    partner_display.admin_order_field = 'partner__name'

    def payment_method_display(self, obj):
        return obj.get_payment_method_display()
    payment_method_display.short_description = _('Payment Method')
    payment_method_display.admin_order_field = 'payment_method'

    def schedule_display(self, obj):
        return obj.schedule_display
    schedule_display.short_description = _('Schedule')
    schedule_display.admin_order_field = 'payout_schedule'


@admin.register(Earnings)
class EarningsAdmin(admin.ModelAdmin):
    list_display = (
        'partner_display',
        'amount',
        'date_display',
        'source_display',
        'status_display',
        'payout_link',
        'referral_link'
    )
    list_filter = (
        'status',
        'source',
        'created_at'  # 'date' field doesn't exist; using timestamps instead
    )
    search_fields = (
        'partner__user__email',
        'partner__user__first_name',
        'partner__user__last_name',
        'referral__client_name',
        'referral__client_email'
    )
    readonly_fields = (
        'created_at',
        'updated_at',
        'payout_link',
        'referral_link'
    )
    fieldsets = (
        (None, {
            'fields': (
                'partner',
                'amount',
                'source',
                'status',
                'notes'
            )
        }),
        (_('Related Objects'), {
            'fields': (
                'referral_link',
                'payout_link'
            ),
            'classes': ('collapse',)
        }),
        (_('Timestamps'), {
            'fields': (
                'created_at',
                'updated_at'
            ),
            'classes': ('collapse',)
        }),
    )
    actions = ['mark_as_available', 'mark_as_processing', 'mark_as_paid']

    def partner_display(self, obj):
        return obj.partner.name
    partner_display.short_description = _('Partner')
    partner_display.admin_order_field = 'partner__name'

    def source_display(self, obj):
        return obj.get_source_display()
    source_display.short_description = _('Source')
    source_display.admin_order_field = 'source'

    def status_display(self, obj):
        return obj.get_status_display()
    status_display.short_description = _('Status')
    status_display.admin_order_field = 'status'

    def date_display(self, obj):
        return obj.created_at.date()
    date_display.short_description = _('Date')
    date_display.admin_order_field = 'created_at'

    def payout_link(self, obj):
        if hasattr(obj, 'payout') and obj.payout:
            return format_html(
                '<a href="{}">{}</a>',
                f"/admin/payouts/payout/{obj.payout.id}/change/",
                obj.payout.id
            )
        return None
    payout_link.short_description = _('Payout')

    def referral_link(self, obj):
        if hasattr(obj, 'referral') and obj.referral:
            return format_html(
                '<a href="{}">{}</a>',
                f"/admin/referrals_management/referral/{obj.referral.id}/change/",
                obj.referral.client_name
            )
        return None
    referral_link.short_description = _('Referral')

    def mark_as_available(self, request, queryset):
        updated = 0
        for earning in queryset:
            if earning.mark_as_available():
                updated += 1
        self.message_user(request, f"{updated} earnings marked as available.")
    mark_as_available.short_description = _("Mark selected earnings as available")

    def mark_as_processing(self, request, queryset):
        updated = 0
        for earning in queryset:
            if earning.mark_as_processing():
                updated += 1
        self.message_user(request, f"{updated} earnings marked as processing.")
    mark_as_processing.short_description = _("Mark selected earnings as processing")

    def mark_as_paid(self, request, queryset):
        updated = 0
        for earning in queryset:
            if earning.mark_as_paid():
                updated += 1
        self.message_user(request, f"{updated} earnings marked as paid.")
    mark_as_paid.short_description = _("Mark selected earnings as paid")
