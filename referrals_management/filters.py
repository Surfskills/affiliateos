# filters.py
import django_filters
from .models import Referral
from django.utils import timezone
from datetime import timedelta

class ReferralFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(field_name='status')
    product = django_filters.CharFilter(field_name='product_name')
    date = django_filters.CharFilter(method='filter_by_date')
    
    class Meta:
        model = Referral
        fields = ['status', 'product']
    
    def filter_by_date(self, queryset, name, value):
        today = timezone.now().date()
        
        if value == 'today':
            return queryset.filter(date_submitted__date=today)
        elif value == 'thisWeek':
            start_of_week = today - timedelta(days=today.weekday())
            return queryset.filter(date_submitted__date__gte=start_of_week)
        elif value == 'thisMonth':
            return queryset.filter(date_submitted__month=today.month, date_submitted__year=today.year)
        elif value == 'last3Months':
            three_months_ago = today - timedelta(days=90)
            return queryset.filter(date_submitted__date__gte=three_months_ago)
        return queryset