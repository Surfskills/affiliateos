from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Count, Sum, Case, When, F, IntegerField
from django.utils import timezone
from datetime import timedelta
from rest_framework import viewsets, status, permissions 
import secrets
from django.db.models.functions import TruncMonth

from payouts.models import Payout
from referrals_management.models import Referral
from .models import PartnerOnboardingLink, PartnerProfile, Product
from .serializers import PartnerOnboardingLinkSerializer, PartnerProfileSerializer, PartnerDetailSerializer
from rest_framework.permissions import IsAuthenticated

class PartnerViewSet(viewsets.ModelViewSet):
    # permission_classes = [IsAuthenticated]
    queryset = PartnerProfile.objects.all()
    serializer_class = PartnerProfileSerializer
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=['get'], url_path='my_profile', permission_classes=[IsAuthenticated])
    def my_profile(self, request):
        """
        Returns the partner profile for the currently authenticated user.
        """
        try:
            profile = PartnerProfile.objects.get(user=request.user)
        except PartnerProfile.DoesNotExist:
            return Response({"error": "Partner not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(profile)
        return Response(serializer.data)

    def get_queryset(self):
        """
        Customize the queryset to include calculated fields needed for the frontend
        """
        queryset = PartnerProfile.objects.select_related('user').prefetch_related(
            'user__referrals', 
            'selected_products'
        ).annotate(
    total_referrals_count=Count('user__referrals'),
    converted_referrals_count=Count(
        Case(
            When(user__referrals__status='converted', then=1),
            output_field=IntegerField()
        )
    )
)

        
        # Add calculated fields for earnings (adjust as needed based on your models)
        # Assuming the earnings model has a partner field related to PartnerProfile
        if hasattr(self, 'earnings'):
                queryset = queryset.annotate(
                    total_earnings=Sum(
                        Case(
                            When(earnings__status__in=['available', 'paid'], then=F('earnings__amount')),
                            default=0,
                            output_field=IntegerField()
                        )
                    ),
                    available_earnings=Sum(
                        Case(
                            When(earnings__status='available', then=F('earnings__amount')),
                            default=0,
                            output_field=IntegerField()
                        )
                    ),
                    pending_earnings=Sum(
                        Case(
                            When(earnings__status='pending', then=F('earnings__amount')),
                            default=0,
                            output_field=IntegerField()
                        )
                    )
                )
            
        return queryset

        # Add calculated fields for total earnings, available earnings, and pending earnings        
    def list(self, request):
        """
        Override list method to return partner profiles in the format needed by the frontend
        """
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        
        # Add conversion_rate calculation where needed
        partners_data = serializer.data
        for partner in partners_data:
            total_referrals = partner.get('total_referrals', 0)
            converted_referrals = partner.get('converted_referrals', 0)
            
            if total_referrals > 0:
                partner['conversion_rate'] = round((converted_referrals / total_referrals) * 100)
            else:
                partner['conversion_rate'] = 0
        
        return Response(partners_data)
    
    
    def retrieve(self, request, pk=None):
        """
        Override retrieve method to return detailed partner data
        """
        try:
            partner = self.get_object()
        except:
            return Response({"error": "Partner not found"}, status=status.HTTP_404_NOT_FOUND)
        
        # Get basic partner profile data
        serializer = PartnerDetailSerializer(partner)
        partner_data = serializer.data
        
        # Get all converted referrals (unsliced)
        converted_referrals = partner.user.referrals.filter(status='converted')
        
        # Calculate total commission from all converted referrals
        total_commission = converted_referrals.aggregate(
            total=Sum('actual_commission')
        )['total'] or 0
        
        # Get all referrals for calculations (unsliced)
        all_referrals = partner.user.referrals.all()
        
        # Get recent referrals for display (collect data before slicing)
        recent_referrals_data = list(all_referrals.order_by('-date_submitted')[:10].values(
            'id', 'client_name', 'date_submitted', 'expected_implementation_date',
            'status', 'potential_commission', 'actual_commission', 'product__name'
        ))
        
        # Now, calculate the referrals by product and other details
        referrals_by_product = []
        for product in partner.selected_products.all():
            # Work with unsliced querysets for calculations
            product_referrals = all_referrals.filter(product=product)
            converted_count = product_referrals.filter(status='converted').count()
            total_count = product_referrals.count()
            conversion_rate = 0
            if total_count > 0:
                conversion_rate = round((converted_count / total_count) * 100)

            referrals_by_product.append({
                'product_name': product.name,
                'count': total_count,
                'conversion_rate': conversion_rate,
                'total_commission': product_referrals.filter(status='converted').aggregate(
                    total=Sum('actual_commission')
                )['total'] or 0
            })

        # Get earnings data (adjust based on your models)
        recent_earnings = []
        earnings_by_month = []
        
        # Assuming you have an Earnings model with these fields
        if hasattr(partner, 'earnings'):
            recent_earnings = list(partner.earnings.all().order_by('-created_at')[:10].values(
                'id', 'amount', 'status', 'created_at', 'source'
            ))
            
            # Calculate earnings by month for the last 6 months
            six_months_ago = timezone.now() - timedelta(days=180)
            monthly_earnings = partner.earnings.filter(
                created_at__gte=six_months_ago
            ).values(
                'created_at__year', 'created_at__month'
            ).annotate(
                year=F('created_at__year'),
                month=F('created_at__month'),
                amount=Sum('amount'),
                referrals_count=Count('referral', distinct=True)
            ).order_by('year', 'month')
            
            for month_data in monthly_earnings:
                # Convert month number to name
                month_name = {
                    1: 'January', 2: 'February', 3: 'March', 4: 'April', 
                    5: 'May', 6: 'June', 7: 'July', 8: 'August',
                    9: 'September', 10: 'October', 11: 'November', 12: 'December'
                }.get(month_data['month'], 'Unknown')
                
                earnings_by_month.append({
                    'month': month_name,
                    'year': month_data['year'],
                    'amount': month_data['amount'],
                    'referrals_count': month_data['referrals_count']
                })
        
        # Calculate metrics
        metrics = {
            'available_earnings': partner_data.get('available_earnings', 0),
            'pending_earnings': partner_data.get('pending_earnings', 0),
            'total_earnings': partner_data.get('total_earnings', 0),
            'total_referrals': partner_data.get('total_referrals', 0),
            'referral_status_counts': {
                'converted': {
                    'count': partner_data.get('converted_referrals', 0),
                    'total_commission': converted_referrals.aggregate(  # Use the unsliced queryset
                        total=Sum('actual_commission')
                    )['total'] or 0
                },
                'pending': {
                    'count': all_referrals.filter(status='pending').count(),  # Use a direct filter
                    'total_commission': all_referrals.filter(status='pending').aggregate(
                        total=Sum('potential_commission')
                    )['total'] or 0
                }
            }
        }
        
        # Construct the response data
        response_data = {
            'partner': partner_data,
            'referrals': {
                'recent': recent_referrals_data,
                'by_product': referrals_by_product
            },
            'earnings': {
                'recent': recent_earnings,
                'by_month': earnings_by_month
            },
            'metrics': metrics
        }
        
        # Format the data for the frontend
        # Convert field names to match frontend expectations
        for referral in response_data['referrals']['recent']:
            referral['dateSubmitted'] = referral.pop('date_submitted')
            referral['clientName'] = referral.pop('client_name')
            referral['expectedImplementationDate'] = referral.pop('expected_implementation_date')
            referral['potentialCommission'] = referral.pop('potential_commission')
            referral['actualCommission'] = referral.pop('actual_commission')
            referral['product'] = referral.pop('product__name')
            
            # Add status display
            status_mapping = {
                'pending': 'Pending',
                'contacted': 'Contacted',
                'qualified': 'Qualified',
                'converted': 'Converted',
                'rejected': 'Rejected'
            }
            referral['statusDisplay'] = status_mapping.get(referral['status'], referral['status'].capitalize())
        
        for earning in response_data['earnings']['recent']:
            earning['requestDate'] = earning.pop('created_at')
        
        return Response(response_data)
    
    @action(detail=False, methods=['get'], url_path='dashboard')
    def dashboard(self, request):
        """
        Custom endpoint to get dashboard statistics
        """
        total_partners = PartnerProfile.objects.count()
        
        # New partners this month
        current_month = timezone.now().month
        current_year = timezone.now().year
        new_partners_this_month = PartnerProfile.objects.filter(
            created_at__month=current_month,
            created_at__year=current_year
        ).count()
        
        # Average conversion rate
        # This calculation depends on your specific data model
        # This is a simplified version
        partners_with_referrals = PartnerProfile.objects.annotate(
            total_refs=Count('user__referrals'),
            converted_refs=Count(
                Case(
                    When(user__referrals__status='converted', then=1),
                    output_field=IntegerField()
                )
            )
        ).filter(total_refs__gt=0)
        
        total_conversion_rate = 0
        partners_count = partners_with_referrals.count()
        
        if partners_count > 0:
            for partner in partners_with_referrals:
                if partner.total_refs > 0:
                    partner_rate = (partner.converted_refs / partner.total_refs) * 100
                    total_conversion_rate += partner_rate
                    
            average_conversion_rate = round(total_conversion_rate / partners_count)
        else:
            average_conversion_rate = 0
        
        # Total earnings
        # Adjust based on your data model
        total_earnings = 0
        
        # Status breakdown
        status_breakdown = {
            status_choice[0]: PartnerProfile.objects.filter(status=status_choice[0]).count()
            for status_choice in PartnerProfile.Status.choices
        }
        
        # Partner growth (last 6 months)
        months = []
        partner_counts = []
        
        for i in range(5, -1, -1):
            month_date = timezone.now() - timedelta(days=30 * i)
            month_name = month_date.strftime('%b')
            months.append(month_name)
            
            # Count partners created until that month
            count = PartnerProfile.objects.filter(
                created_at__lte=month_date
            ).count()
            partner_counts.append(count)
        
        partner_growth = {
            'labels': months,
            'data': partner_counts
        }
        
        stats = {
            'totalPartners': total_partners,
            'newPartnersThisMonth': new_partners_this_month,
            'averageConversionRate': average_conversion_rate,
            'totalEarnings': total_earnings,
            'statusBreakdown': status_breakdown,
            'partnerGrowth': partner_growth
        }
        
        return Response(stats)
    
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """
        Endpoint to update partner status
        """
        partner = self.get_object()
        new_status = request.data.get('status')
        
        if new_status not in [status[0] for status in PartnerProfile.Status.choices]:
            return Response(
                {"error": f"Invalid status. Choose from {[status[0] for status in PartnerProfile.Status.choices]}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        partner.status = new_status
        partner.save()
        
        return Response(self.get_serializer(partner).data)
    # BACKEND FIX - Django View
    @action(detail=False, methods=['get'], url_path='recent-activities')
    def recent_activities(self, request):
            """
            Custom endpoint for recent activities with proper date handling and name formatting
            """
            # Get recent partners (last 5)
            recent_partners = PartnerProfile.objects.select_related('user').order_by('-created_at')[:5].values(
                'id', 'user__id', 'user__first_name', 'user__last_name', 'created_at'
            )
            
            # Get recent referrals (last 5)
            recent_referrals = Referral.objects.select_related('partner__user', 'product').order_by('-date_submitted')[:5].values(
                'id', 'client_name', 'status', 'date_submitted', 'actual_commission', 'product__name',
                'partner__id', 'partner__user__id', 'partner__user__first_name', 'partner__user__last_name'
            )
            
            # Get recent payouts (last 5)
            recent_payouts = Payout.objects.select_related('partner__user').order_by('-processed_date')[:5].values(
                'id', 'amount', 'processed_date', 'status',
                'partner__id', 'partner__user__id', 'partner__user__first_name', 'partner__user__last_name'
            )
            
            activities = []
            
            # Process partners
            for partner in recent_partners:
                # Ensure first and last name exist
                first_name = partner.get('user__first_name') or ''
                last_name = partner.get('user__last_name') or ''
                full_name = f"{first_name} {last_name}".strip()
                if not full_name:
                    full_name = "Unknown"
                
                timestamp = partner.get('created_at')
                activities.append({
                    'id': partner['id'],
                    'type': 'new_partner',
                    'name': f"New partner: {full_name}",
                    'timestamp': timestamp.isoformat() if timestamp else None,
                    'amount': None,
                    'user_id': partner.get('user__id'),
                    'associated_name': full_name,
                    'associated_type': 'partner'
                })
            
            # Process referrals
            for referral in recent_referrals:
                # Ensure client name exists and is not empty
                client_name = referral.get('client_name')
                if not client_name or client_name.strip() == '':
                    client_name = "Unknown Client"
                
                # Get product name if available
                product_name = referral.get('product__name')
                
                # Get partner information
                first_name = referral.get('partner__user__first_name') or ''
                last_name = referral.get('partner__user__last_name') or ''
                partner_name = f"{first_name} {last_name}".strip()
                if not partner_name:
                    partner_name = "Unknown Partner"
                
                # Format the activity name with more details
                activity_name = f"Referral {referral['status']}: {client_name}"
                if product_name:
                    activity_name += f" for {product_name}"
                
                timestamp = referral.get('date_submitted')
                activities.append({
                    'id': referral['id'] + 1000,  # Offset to avoid ID conflicts
                    'type': 'referral_status',
                    'name': activity_name,
                    'timestamp': timestamp.isoformat() if timestamp else None,
                    'amount': float(referral['actual_commission']) if referral['actual_commission'] else None,
                    'user_id': referral.get('partner__user__id'),
                    'partner_id': referral.get('partner__id'),
                    'associated_name': partner_name,
                    'client_name': client_name,
                    'status': referral.get('status'),
                    'associated_type': 'partner'
                })
            
            # Process payouts
            for payout in recent_payouts:
                # Ensure partner name exists
                first_name = payout.get('partner__user__first_name') or ''
                last_name = payout.get('partner__user__last_name') or ''
                partner_name = f"{first_name} {last_name}".strip()
                if not partner_name:
                    partner_name = "Unknown Partner"
                
                status = payout.get('status', 'processed')
                
                timestamp = payout.get('processed_date')
                activities.append({
                    'id': payout['id'] + 2000,  # Offset to avoid ID conflicts
                    'type': 'payout_processed',
                    'name': f"Payout {status} for {partner_name}",
                    'timestamp': timestamp.isoformat() if timestamp else None,
                    'amount': float(payout['amount']) if payout['amount'] else None,
                    'user_id': payout.get('partner__user__id'),
                    'partner_id': payout.get('partner__id'),
                    'associated_name': partner_name,
                    'status': status,
                    'associated_type': 'partner'
                })
            
            # Only include activities with valid timestamps and sort by timestamp (newest first)
            activities_with_timestamps = [a for a in activities if a['timestamp'] is not None]
            
            # If we have no activities with timestamps, include all and add a default timestamp
            if not activities_with_timestamps and activities:
                from datetime import datetime
                current_time = datetime.now().isoformat()
                for activity in activities:
                    activity['timestamp'] = current_time
                activities_with_timestamps = activities
            
            activities_sorted = sorted(
                activities_with_timestamps,
                key=lambda x: x['timestamp'],
                reverse=True
            )[:10]
            
            return Response(activities_sorted)
    
    # Add this to your PartnerViewSet
    @action(detail=False, methods=['get'], url_path='stats/referrals')
    def referral_stats(self, request):
        """
        Endpoint to get referral statistics for charts
        """
        from django.db.models.functions import TruncMonth
        from django.db.models import Count
        
        # Get referrals for the last 6 months grouped by month
        six_months_ago = timezone.now() - timedelta(days=180)
        
        monthly_stats = (
            Referral.objects
            .filter(date_submitted__gte=six_months_ago)
            .annotate(month=TruncMonth('date_submitted'))
            .values('month')
            .annotate(count=Count('id'))
            .order_by('month')
        )
        
        # Format the data with month names
        formatted_stats = []
        month_names = {
            1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr',
            5: 'May', 6: 'Jun', 7: 'Jul', 8: 'Aug',
            9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'
        }
        
        for stat in monthly_stats:
            month = stat['month'].month
            year = stat['month'].year
            formatted_stats.append({
                'month': f"{month_names[month]} {str(year)[-2:]}",
                'count': stat['count']
            })
        
        return Response({
            'monthly_stats': formatted_stats,
            'total_referrals': Referral.objects.count()
        })
    @action(detail=False, methods=['get'], url_path='monthly-stats')
    def monthly_stats(self, request):
        """
        Endpoint to get monthly statistics for charts with explicit default values
        """
        try:
            profile = PartnerProfile.objects.get(user=request.user)
        except PartnerProfile.DoesNotExist:
            return Response({"error": "Partner not found"}, status=status.HTTP_404_NOT_FOUND)

        # Get data for the last 6 months
        six_months_ago = timezone.now() - timedelta(days=180)
        
        # Get referrals by month
        monthly_referrals = {}
        referrals_data = (
            Referral.objects
            .filter(partner=profile, date_submitted__gte=six_months_ago)
            .annotate(month=TruncMonth('date_submitted'))
            .values('month')
            .annotate(count=Count('id'))
        )
        
        # Convert to a more easily accessible format
        for item in referrals_data:
            month_key = f"{item['month'].year}-{item['month'].month}"
            monthly_referrals[month_key] = item['count']
        
        # Get earnings by month
        monthly_earnings = {}
        if hasattr(profile, 'earnings'):
            earnings_data = (
                profile.earnings
                .filter(created_at__gte=six_months_ago)
                .annotate(month=TruncMonth('created_at'))
                .values('month')
                .annotate(amount=Sum('amount'))
            )
            
            for item in earnings_data:
                month_key = f"{item['month'].year}-{item['month'].month}"
                monthly_earnings[month_key] = float(item['amount'])
        
        # Format the data with month names
        month_names = {
            1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr',
            5: 'May', 6: 'Jun', 7: 'Jul', 8: 'Aug',
            9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'
        }
        
        # Generate the last 6 months in reverse chronological order
        response_data = []
        now = timezone.now()
        for i in range(5, -1, -1):
            # Calculate month by going back i months from current month
            target_month = now.month - i
            target_year = now.year
            
            # Handle month wrapping around
            while target_month <= 0:
                target_month += 12
                target_year -= 1
            
            month_key = f"{target_year}-{target_month}"
            month_display = f"{month_names[target_month]} {str(target_year)[-2:]}"
            
            # Get data with explicit default values
            response_data.append({
                'month': month_display,
                'referrals': monthly_referrals.get(month_key, 0),  # Default to 0 if no data
                'earnings': monthly_earnings.get(month_key, 0.0)   # Default to 0.0 if no data
            })
        
        # Log the response for debugging
        print(f"Monthly stats response: {response_data}")
        
        return Response(response_data)

class PartnerOnboardingLinkViewSet(viewsets.ModelViewSet):
    queryset = PartnerOnboardingLink.objects.all()
    serializer_class = PartnerOnboardingLinkSerializer
    permission_classes = [permissions.IsAdminUser]  # Only admins can manage onboarding links

    def create(self, request, *args, **kwargs):
        # Generate a unique token
        token = secrets.token_urlsafe(32)

        # Set expiration (default 30 days)
        expires_at = timezone.now() + timedelta(days=30)

        # Prepare the data (excluding created_by)
        data = {
            'token': token,
            'expires_at': expires_at,
            'is_active': True,
            **request.data
        }

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        link = self.get_object()
        link.is_active = False
        link.save()
        return Response({'status': 'link deactivated'})

    @action(detail=True, methods=['post'])
    def extend(self, request, pk=None):
        link = self.get_object()
        days = int(request.data.get('days', 30))
        link.expires_at = link.expires_at + timedelta(days=days)
        link.save()
        return Response({'status': 'link extended', 'new_expiry': link.expires_at})