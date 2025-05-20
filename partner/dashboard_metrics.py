from django.db import models
from django.db.models import Count, Sum, Avg, F, Q, ExpressionWrapper, fields
from django.utils import timezone
from datetime import timedelta, datetime
from decimal import Decimal

from documents_management.models import Document
from payouts.models import Payout, Earnings
from partner.models import PartnerProfile, Product, Testimonial
from referrals_management.models import Referral
from resources.models import Resource



class DashboardMetrics:
    """
    Class to calculate and provide metrics for admin dashboard
    """
    
    @classmethod
    def get_all_metrics(cls):
        """Get all dashboard metrics in a single call"""
        return {
            'overview': cls.get_overview_metrics(),
            'referrals': cls.get_referral_metrics(),
            'partners': cls.get_partner_metrics(),
            'earnings': cls.get_earnings_metrics(),
            'payouts': cls.get_payout_metrics(),
            'resources': cls.get_resource_metrics(),
            'documents': cls.get_document_metrics(),
            'products': cls.get_product_metrics(),
            'timeline': cls.get_timeline_metrics(),
        }
    
    @classmethod
    def get_overview_metrics(cls):
        """Return high-level overview metrics for the dashboard"""
        now = timezone.now()
        month_ago = now - timedelta(days=30)
        
        # Get total counts
        total_referrals = Referral.objects.count()
        total_partners = PartnerProfile.objects.count()
        total_products = Product.objects.count()
        
        # Get active partners (logged in within last 30 days)
        # FIXED: Handle case where last_login might be NULL
        active_partners = PartnerProfile.objects.filter(
        status='active'  # Changed from last_login check
    ).count()
        
        # Get total earnings and payouts
        total_earnings = Earnings.objects.exclude(status='cancelled').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        
        total_payouts = Payout.objects.filter(
            status='completed'
        ).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        
        # Get conversion rate
        converted_referrals = Referral.objects.filter(
            status='converted'
        ).count()
        
        conversion_rate = 0
        if total_referrals > 0:
            conversion_rate = (converted_referrals / total_referrals) * 100
        
        # Get month-to-month growth
        current_month_referrals = Referral.objects.filter(
            date_submitted__gte=month_ago
        ).count()
        
        two_months_ago = now - timedelta(days=60)
        previous_month_referrals = Referral.objects.filter(
            date_submitted__gte=two_months_ago,
            date_submitted__lt=month_ago
        ).count()
        
        # FIXED: Handle zero previous month referrals case better
        if previous_month_referrals > 0:
            referral_growth = ((current_month_referrals - previous_month_referrals) / previous_month_referrals) * 100
        elif current_month_referrals > 0:
            # If we have current referrals but no previous ones, that's "infinite" growth
            # but we'll cap it at 100% for display purposes
            referral_growth = 100.0
        else:
            referral_growth = 0
        
        # Calculate active partner percentage with null-safe handling
        active_percentage = 0
        if total_partners > 0:
            active_percentage = (active_partners / total_partners) * 100
        
        # Calculate payout percentage with null-safe handling
        payout_percentage = 0
        if total_earnings > 0:
            payout_percentage = (total_payouts / total_earnings) * 100
        
        return {
            'total_referrals': total_referrals,
            'total_partners': total_partners,
            'total_products': total_products,
            'active_partners': active_partners,
            'active_partners_percentage': active_percentage,
            'total_earnings': total_earnings,
            'total_payouts': total_payouts,
            'payout_percentage': payout_percentage,
            'conversion_rate': conversion_rate, 
            'referral_growth': referral_growth,
            'current_month_referrals': current_month_referrals,
            'last_month_referrals': previous_month_referrals,
        }
    @classmethod
    def get_referral_metrics(cls):
        """Return detailed referral metrics"""
        now = timezone.now()
        
        # Time ranges
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)
        quarter_ago = now - timedelta(days=90)
        year_ago = now - timedelta(days=365)
        
        # Base queries
        referrals = Referral.objects
        
        # Status counts
        status_counts = referrals.values('status').annotate(count=Count('id'))
        status_dict = {item['status']: item['count'] for item in status_counts}
        
        # Timeline distribution
        timeline_counts = referrals.values('timeline').annotate(count=Count('id'))
        timeline_dict = {item['timeline']: item['count'] for item in timeline_counts}
        
        # Time-based metrics
        today_referrals = referrals.filter(date_submitted__gte=today).count()
        yesterday_referrals = referrals.filter(
            date_submitted__gte=yesterday, 
            date_submitted__lt=today
        ).count()
        
        weekly_referrals = referrals.filter(date_submitted__gte=week_ago).count()
        monthly_referrals = referrals.filter(date_submitted__gte=month_ago).count()
        quarterly_referrals = referrals.filter(date_submitted__gte=quarter_ago).count()
        yearly_referrals = referrals.filter(date_submitted__gte=year_ago).count()
        
        # Average time to conversion
        converted_referrals = Referral.objects.filter(status='converted')
        avg_time_to_conversion = None
        
        if converted_referrals.exists():
            # We need status timeline data to calculate this properly
            conversion_times = []
            for referral in converted_referrals:
                timeline_entries = referral.status_changes.order_by('timestamp')
                first_entry = timeline_entries.first()
                last_entry = timeline_entries.filter(status='converted').first()
                if first_entry and last_entry:
                    conversion_time = last_entry.timestamp - first_entry.timestamp
                    conversion_times.append(conversion_time.total_seconds())
                    
            if conversion_times:
                avg_seconds = sum(conversion_times) / len(conversion_times)
                avg_time_to_conversion = avg_seconds / (60 * 60 * 24)  # Convert to days
        
        # Calculate daily referral counts for the past 30 days
        daily_counts = []
        for i in range(30):
            day = now - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            count = referrals.filter(
                date_submitted__gte=day_start,
                date_submitted__lt=day_end
            ).count()
            daily_counts.append({
                'date': day_start.strftime('%Y-%m-%d'),
                'count': count
            })
        
        # Potential vs actual commission
        total_potential = referrals.aggregate(
            total=Sum('potential_commission')
        )['total'] or 0
        
        total_actual = referrals.filter(
            status='converted'
        ).aggregate(
            total=Sum('actual_commission')
        )['total'] or 0
        
        realization_rate = (total_actual / total_potential * 100) if total_potential > 0 else 0
        
        return {
            'total_count': referrals.count(),
            'status_distribution': status_dict,
            'timeline_distribution': timeline_dict,
            'today_count': today_referrals,
            'yesterday_count': yesterday_referrals,
            'day_growth': ((today_referrals - yesterday_referrals) / yesterday_referrals * 100) if yesterday_referrals > 0 else 0,
            'weekly_count': weekly_referrals,
            'monthly_count': monthly_referrals,
            'quarterly_count': quarterly_referrals,
            'yearly_count': yearly_referrals,
            'avg_conversion_time_days': avg_time_to_conversion,
            'daily_counts': daily_counts,
            'total_potential_commission': total_potential,
            'total_actual_commission': total_actual,
            'commission_realization_rate': realization_rate,
        }
    @classmethod
    def get_partner_metrics(cls):
        """Return partner-related metrics"""
        now = timezone.now()
        month_ago = now - timedelta(days=30)
        
        # Partner status distribution
        status_counts = PartnerProfile.objects.values('status').annotate(
            count=Count('id')
        )
        status_dict = {item['status']: item['count'] for item in status_counts}
        
        # New partners in the last 30 days
        new_partners = PartnerProfile.objects.filter(
            created_at__gte=month_ago
        ).count()
        
        # Use status distribution for active/inactive instead of last_login
        # Assuming 'active' is a status in your status field
        total_partners = PartnerProfile.objects.count()
        active_partners = status_dict.get('active', 0)
        inactive_partners = total_partners - active_partners
        
        # Calculate activity rate with null safety
        activity_rate = 0
        if total_partners > 0:
            activity_rate = (active_partners / total_partners) * 100
        
        # Top partners by referral count
        top_partners_by_referrals = PartnerProfile.objects.annotate(
            referral_count=Count('referrals')
        ).order_by('-referral_count')[:10]
        
        top_partners_referrals = [
            {
                'id': partner.id,
                'name': partner.name,
                'company': partner.company,
                'referral_count': partner.referral_count
            }
            for partner in top_partners_by_referrals
        ]
        
        # Top partners by conversion
        top_converter_data = PartnerProfile.objects.annotate(
            converted_count=Count('referrals', filter=Q(referrals__status='converted')),
            total_count=Count('referrals')
        ).filter(total_count__gt=0).values(
            'id', 'name', 'company', 'converted_count', 'total_count'
        ).order_by('-converted_count')[:10]
        
        top_converters_list = []
        for data in top_converter_data:
            conversion_rate = (data['converted_count'] * 100.0 / data['total_count']) if data['total_count'] > 0 else 0
            
            top_converters_list.append({
                'id': data['id'],
                'name': data['name'],
                'company': data['company'],
                'converted': data['converted_count'],
                'total': data['total_count'],
                'conversion_rate': conversion_rate
            })
        
        # Sort by conversion rate
        top_converters_list.sort(key=lambda x: x['conversion_rate'], reverse=True)
        
        # Top partners by earnings
        top_earners = PartnerProfile.objects.annotate(
            annotated_total_earnings=Sum('earnings__amount', filter=~Q(earnings__status='cancelled'))
        ).filter(annotated_total_earnings__gt=0).order_by('-annotated_total_earnings')[:10]

        top_earners_list = [
            {
                'id': partner.id,
                'name': partner.name,
                'company': partner.company,
                'total_earnings': partner.annotated_total_earnings
            }
            for partner in top_earners
        ]
        
        # Partners by product selection
        product_distribution = Product.objects.annotate(
            partner_count=Count('partners')
        ).values('name', 'partner_count').order_by('-partner_count')
        
        product_partners = [
            {
                'product': item['name'],
                'partner_count': item['partner_count']
            }
            for item in product_distribution
        ]
        
        return {
            'total_partners': total_partners,
            'status_distribution': status_dict,
            'new_partners_last_30_days': new_partners,
            'active_partners': active_partners,
            'inactive_partners': inactive_partners,
            'activity_rate': activity_rate,
            'top_partners_by_referrals': top_partners_referrals,
            'top_partners_by_conversion': top_converters_list,
            'top_partners_by_earnings': top_earners_list,
            'product_distribution': product_partners,
        }
        
    @classmethod
    def get_earnings_metrics(cls):
        """Return earnings-related metrics"""
        now = timezone.now()
        month_ago = now - timedelta(days=30)
        
        # Total earnings by status
        status_totals = Earnings.objects.values('status').annotate(
            total=Sum('amount'),
            count=Count('id')
        )
        
        status_dict = {
            item['status']: {
                'total': item['total'],
                'count': item['count']
            } for item in status_totals
        }
        
        # Monthly earnings trend
        monthly_earnings = []
        for i in range(12):
            month_end = now.replace(day=1) - timedelta(days=1)
            month_start = month_end.replace(day=1)
            
            if i > 0:
                month_end = month_start - timedelta(days=1)
                month_start = month_end.replace(day=1)
            
            month_total = Earnings.objects.filter(
                date__gte=month_start,
                date__lte=month_end
            ).aggregate(total=Sum('amount'))['total'] or 0
            
            monthly_earnings.append({
                'month': month_start.strftime('%Y-%m'),
                'total': month_total
            })
            
            now = month_start  # Move to previous month
        
        monthly_earnings.reverse()  # Show oldest to newest
        
        # Source distribution
        source_totals = Earnings.objects.values('source').annotate(
            total=Sum('amount'),
            count=Count('id')
        )
        
        source_dict = {
            item['source']: {
                'total': item['total'],
                'count': item['count']
            } for item in source_totals
        }
        
        # Pending vs paid ratio
        pending_total = Earnings.objects.filter(
            status__in=['pending', 'pending_approval', 'available', 'processing']
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        paid_total = Earnings.objects.filter(
            status='paid'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        # Recent earnings
        recent_earnings = Earnings.objects.select_related(
            'partner', 'referral'
        ).order_by('-created_at')[:20]
        
        recent_list = [
            {
                'id': earning.id,
                'partner': earning.partner.name,
                'amount': earning.amount,
                'source': earning.source,
                'status': earning.status,
                'date': earning.date,
                'referral_id': earning.referral.id if earning.referral else None,
                'referral_client': earning.referral.client_name if earning.referral else None
            }
            for earning in recent_earnings
        ]
        
        return {
            'total_earnings': sum(item['total'] for item in status_dict.values()),
            'status_distribution': status_dict,
            'monthly_trend': monthly_earnings,
            'source_distribution': source_dict,
            'pending_total': pending_total,
            'paid_total': paid_total,
            'payout_ratio': (paid_total / (pending_total + paid_total) * 100) if (pending_total + paid_total) > 0 else 0,
            'recent_earnings': recent_list,
        }
    
    @classmethod
    def get_payout_metrics(cls):
        """Return payout-related metrics"""
        # Status distribution
        status_counts = Payout.objects.values('status').annotate(
            count=Count('id'),
            total=Sum('amount')
        )
        
        status_dict = {
            item['status']: {
                'count': item['count'],
                'total': item['total']
            } for item in status_counts
        }
        
        # Payment method distribution
        method_counts = Payout.objects.values('payment_method').annotate(
            count=Count('id'),
            total=Sum('amount')
        )
        
        method_dict = {
            item['payment_method']: {
                'count': item['count'],
                'total': item['total']
            } for item in method_counts
        }
        
        # Monthly payout trend
        monthly_payouts = []
        now = timezone.now()
        
        for i in range(12):
            month_end = now.replace(day=1) - timedelta(days=1)
            month_start = month_end.replace(day=1)
            
            if i > 0:
                month_end = month_start - timedelta(days=1)
                month_start = month_end.replace(day=1)
            
            month_total = Payout.objects.filter(
                status='completed',
                processed_date__gte=month_start,
                processed_date__lte=month_end
            ).aggregate(total=Sum('amount'))['total'] or 0
            
            monthly_payouts.append({
                'month': month_start.strftime('%Y-%m'),
                'total': month_total
            })
            
            now = month_start  # Move to previous month
        
        monthly_payouts.reverse()  # Show oldest to newest
        
        # Average processing time - FIXED to handle NULL gracefully
        completed_payouts = Payout.objects.filter(
            status='completed',
            processed_date__isnull=False,
            request_date__isnull=False  # Ensure both dates are available
        )
        
        avg_processing_time = None
        if completed_payouts.exists():
            # Use Django's aggregation with ExpressionWrapper for better performance
            time_diff = ExpressionWrapper(
                F('processed_date') - F('request_date'),
                output_field=fields.DurationField()
            )
            
            result = completed_payouts.annotate(
                processing_time=time_diff
            ).aggregate(
                avg_time=Avg('processing_time')
            )
            
            if result['avg_time']:
                # Convert timedelta to hours
                avg_processing_time = result['avg_time'].total_seconds() / (60 * 60)
        
        # Pending payouts - FIXED: ensure proper ordering and handle empty case
        pending_payouts = Payout.objects.filter(
            status__in=['pending', 'processing']
        ).select_related('partner').order_by('request_date')[:10]
        
        pending_list = []
        for payout in pending_payouts:
            if payout.request_date:  # Make sure we have a request date
                pending_list.append({
                    'id': payout.id,
                    'partner': payout.partner.name if payout.partner else "Unknown",
                    'amount': payout.amount,
                    'request_date': payout.request_date,
                    'status': payout.status,
                    'days_pending': (timezone.now() - payout.request_date).days
                })
        
        # If no pending payouts, provide an empty list but don't fail
        
        return {
            'total_payouts': Payout.objects.count(),
            'total_amount_paid': Payout.objects.filter(status='completed').aggregate(
                total=Sum('amount')
            )['total'] or 0,
            'status_distribution': status_dict,
            'payment_method_distribution': method_dict,
            'monthly_trend': monthly_payouts,
            'avg_processing_time_hours': avg_processing_time,
            'pending_payouts': pending_list,
            'pending_amount': Payout.objects.filter(
                status__in=['pending', 'processing']
            ).aggregate(total=Sum('amount'))['total'] or 0,
        }
 
    @classmethod
    def get_resource_metrics(cls):
        """Return metrics related to resources"""
        # Resource type distribution
        type_counts = Resource.objects.values('resource_type').annotate(
            count=Count('id')
        )
        
        type_dict = {
            item['resource_type']: item['count'] for item in type_counts
        }
        
        # Visibility distribution
        visibility_counts = Resource.objects.values('visibility').annotate(
            count=Count('id')
        )
        
        visibility_dict = {
            item['visibility']: item['count'] for item in visibility_counts
        }
        
        # Category distribution
        category_counts = Resource.objects.values(
            'category__name'
        ).annotate(
            count=Count('id')
        ).order_by('-count')
        
        category_dict = {
            item['category__name']: item['count'] for item in category_counts
        }
        
        # Most popular resources (by downloads and views)
        popular_downloads = Resource.objects.order_by('-download_count')[:10]
        popular_views = Resource.objects.order_by('-view_count')[:10]
        
        download_list = [
            {
                'id': resource.id,
                'title': resource.title,
                'type': resource.resource_type,
                'download_count': resource.download_count
            }
            for resource in popular_downloads
        ]
        
        view_list = [
            {
                'id': resource.id,
                'title': resource.title,
                'type': resource.resource_type,
                'view_count': resource.view_count
            }
            for resource in popular_views
        ]
        
        # Total storage used
        total_storage = Resource.objects.aggregate(
            total=Sum('file_size')
        )['total'] or 0
        
        # Storage by resource type
        storage_by_type = Resource.objects.values(
            'resource_type'
        ).annotate(
            total=Sum('file_size')
        )
        
        storage_dict = {
            item['resource_type']: item['total'] for item in storage_by_type
        }
        
        # Recent uploads
        recent_uploads = Resource.objects.order_by('-upload_date')[:10]
        
        recent_list = [
            {
                'id': resource.id,
                'title': resource.title,
                'type': resource.resource_type,
                'category': resource.category.name,
                'upload_date': resource.upload_date,
                'file_size': resource.file_size
            }
            for resource in recent_uploads
        ]
        
        return {
            'total_resources': Resource.objects.count(),
            'type_distribution': type_dict,
            'visibility_distribution': visibility_dict,
            'category_distribution': category_dict,
            'popular_downloads': download_list,
            'popular_views': view_list,
            'total_storage_bytes': total_storage,
            'storage_by_type': storage_dict,
            'recent_uploads': recent_list,
            'total_downloads': Resource.objects.aggregate(
                total=Sum('download_count')
            )['total'] or 0,
            'total_views': Resource.objects.aggregate(
                total=Sum('view_count')
            )['total'] or 0,
        }
    
    @classmethod
    def get_document_metrics(cls):
        """Return metrics related to documents"""
        # Document status distribution
        status_counts = Document.objects.values('status').annotate(
            count=Count('id')
        )
        
        status_dict = {
            item['status']: item['count'] for item in status_counts
        }
        
        # Document type distribution
        type_counts = Document.objects.values('document_type').annotate(
            count=Count('id')
        )
        
        type_dict = {
            item['document_type']: item['count'] for item in type_counts
        }
        
        # Verification metrics
        verified_count = Document.objects.filter(status='verified').count()
        total_count = Document.objects.count()
        verification_rate = (verified_count / total_count * 100) if total_count > 0 else 0
        
        # Documents requiring verification
        pending_verification = Document.objects.filter(
            status='pending'
        ).order_by('updated_at')[:10]
        
        pending_list = [
            {
                'id': doc.id,
                'name': doc.name,
                'type': doc.document_type,
                'user': f"{doc.user.first_name} {doc.user.last_name}",
                'updated_at': doc.updated_at,
                'days_pending': (timezone.now() - doc.updated_at).days
            }
            for doc in pending_verification
        ]
        
        # Missing required documents
        missing_docs = Document.objects.filter(
            status__in=['missing', 'required']
        ).count()
        
        return {
            'total_documents': total_count,
            'status_distribution': status_dict,
            'type_distribution': type_dict,
            'verified_count': verified_count,
            'verification_rate': verification_rate,
            'pending_verification': pending_list,
            'missing_documents': missing_docs,
        }
    @classmethod
    def get_product_metrics(cls):
        """Return metrics related to products"""
        # Referral count by product - FIXED to handle empty referrals
        product_referrals = Product.objects.annotate(
            referral_count=Count('referrals')
        ).values(
            'name', 'referral_count'
        ).order_by('-referral_count')
        
        product_list = [
            {
                'product': item['name'],
                'referral_count': item['referral_count']
            }
            for item in product_referrals
        ]
        
        # Conversion rate by product - IMPROVED to handle edge cases
        product_conversion_data = Product.objects.annotate(
            total_referrals=Count('referrals'),
            converted_referrals=Count('referrals', filter=Q(referrals__status='converted'))
        ).values(
            'name', 'total_referrals', 'converted_referrals'
        )
        
        conversion_list = []
        for item in product_conversion_data:
            # Include products with zero referrals for completeness
            conversion_rate = (item['converted_referrals'] * 100.0 / item['total_referrals']) if item['total_referrals'] > 0 else 0
            
            conversion_list.append({
                'product': item['name'],
                'total': item['total_referrals'],
                'converted': item['converted_referrals'],
                'conversion_rate': conversion_rate
            })
        
        # Sort by conversion rate
        conversion_list.sort(key=lambda x: x['conversion_rate'], reverse=True)
        
        # Product selection by partners
        partner_selections = Product.objects.annotate(
            partner_count=Count('partners')
        ).values(
            'name', 'partner_count'
        ).order_by('-partner_count')
        
        selection_list = [
            {
                'product': item['name'],
                'partner_count': item['partner_count']
            }
            for item in partner_selections
        ]
        
        # Product earnings - IMPROVED with more efficient query approach
        # First gather all products
        all_products = Product.objects.all()
        
        # Build a dictionary to store earnings by product
        product_to_earnings = {}
        for product in all_products:
            product_to_earnings[product.id] = {
                'product': product.name,
                'earnings': Decimal('0.00')
            }
        
        # Get earnings related to each product's referrals in a single query
        referral_earnings = Earnings.objects.exclude(status='cancelled').select_related('referral')
        
        for earning in referral_earnings:
            if earning.referral and earning.referral.product_id:
                product_id = earning.referral.product_id
                if product_id in product_to_earnings:
                    product_to_earnings[product_id]['earnings'] += earning.amount
        
        # Convert to list and sort
        product_earnings = list(product_to_earnings.values())
        product_earnings.sort(key=lambda x: x['earnings'], reverse=True)
        
        return {
            'total_products': Product.objects.count(),
            'active_products': Product.objects.filter(is_active=True).count(),
            'product_referrals': product_list,
            'product_conversion': conversion_list,
            'partner_selections': selection_list,
            'product_earnings': product_earnings[:10],  # Top 10 by earnings
        }
        
    @classmethod
    def get_timeline_metrics(cls):
        """Return timeline metrics for various activities"""
        # This method was called in get_all_metrics but wasn't implemented
        # Adding a simple implementation to avoid errors
        return {
            'recent_activities': [],  # Placeholder for future implementation
        }