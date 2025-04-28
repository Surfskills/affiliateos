# partner/views.py
from datetime import timedelta
from django.utils import timezone

from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from .models import PartnerOnboardingLink, Product, Testimonial, PartnerProfile
from .serializers import (
    PartnerOnboardingLinkSerializer, ProductSerializer, TestimonialSerializer, 
    PartnerProfileSerializer, PartnerProfileLiteSerializer
)
from rest_framework.permissions import AllowAny
from django.db.models import Count, Sum, Q, F
import secrets
from partner import models
from django.db.models.functions import TruncMonth
import logging
logger = logging.getLogger(__name__)

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100

class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'type', 'is_active', 'exclusive']
    search_fields = ['name', 'title', 'description']
    ordering_fields = ['created_at', 'price', 'commission']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by partner if requested
        partner_id = self.request.query_params.get('partner_id')
        if partner_id:
            queryset = queryset.filter(partners__id=partner_id)
            
        return queryset
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Return product statistics"""
        stats = {
            'total_products': Product.objects.count(),
            'active_products': Product.objects.filter(is_active=True).count(),
            'categories': Product.objects.values('category').annotate(count=Count('id')),
            'avg_commission': Product.objects.aggregate(avg=models.Avg('commission'))['avg']
        }
        return Response(stats)

class TestimonialViewSet(viewsets.ModelViewSet):
    queryset = Testimonial.objects.all()
    serializer_class = TestimonialSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['type', 'is_approved']
    search_fields = ['author', 'content', 'company']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by partner if requested
        partner_id = self.request.query_params.get('partner_id')
        if partner_id:
            queryset = queryset.filter(partners__id=partner_id)
            
        return queryset
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        testimonial = self.get_object()
        testimonial.is_approved = True
        testimonial.save()
        serializer = self.get_serializer(testimonial)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        testimonial = self.get_object()
        testimonial.is_approved = False
        testimonial.save()
        serializer = self.get_serializer(testimonial)
        return Response(serializer.data)




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

    
class PartnerProfileViewSet(viewsets.ModelViewSet):
    queryset = PartnerProfile.objects.all()
    # permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'theme']
    search_fields = ['name', 'email', 'company', 'bio']
    ordering_fields = ['created_at', 'name', 'generated_revenue', 'user__referrals__count']
    serializer_class = PartnerProfileSerializer
    
    def get_serializer_class(self):
        if self.action == 'list':
            return PartnerProfileLiteSerializer
        return PartnerProfileSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by product if requested
        product_id = self.request.query_params.get('product_id')
        if product_id:
            queryset = queryset.filter(selected_products__id=product_id)
            
        # Advanced filtering
        min_referrals = self.request.query_params.get('min_referrals')
        if min_referrals:
            queryset = queryset.annotate(
                referral_count=Count('user__referrals')
            ).filter(referral_count__gte=int(min_referrals))
            
        return queryset
    
    @action(detail=False, methods=['post'])
    def create_via_link(self, request):
        """
        Create partner profile via onboarding link
        """
        token = request.data.get('token')
        if not token:
            return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            link = PartnerOnboardingLink.objects.get(
                token=token,
                is_active=True,
                expires_at__gte=timezone.now()
            )
        except PartnerOnboardingLink.DoesNotExist:
            return Response({'error': 'Invalid or expired onboarding link'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if user already has a partner profile
        if PartnerProfile.objects.filter(user=request.user).exists():
            return Response({'error': 'You already have a partner profile'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Create the partner profile
        serializer = self.get_serializer(data={
            **request.data,
            'user': request.user.id,
            'status': 'pending',
            'referral_code': self._generate_referral_code(),
        })
        
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        
        # Update the onboarding link
        link.used_by = request.user
        link.used_at = timezone.now()
        link.save()
        
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
    
    def _generate_referral_code(self):
        """Generate a unique referral code"""
        while True:
            code = secrets.token_urlsafe(8)[:8].upper()
            if not PartnerProfile.objects.filter(referral_code=code).exists():
                return code
            
    @action(detail=False, methods=['get'], url_path='by-referral/(?P<referral_code>[^/.]+)', permission_classes=[AllowAny])
    def by_referral(self, request, referral_code=None):
        try:
            profile = PartnerProfile.objects.get(referral_code=referral_code)
            serializer = self.get_serializer(profile)
            return Response(serializer.data)
        except PartnerProfile.DoesNotExist:
            return Response({"error": "Partner profile not found"}, status=status.HTTP_404_NOT_FOUND)
        
    @action(detail=False, methods=['get'])
    def validate_onboarding_link(self, request):
        """
        Validate an onboarding link token
        """
        token = request.query_params.get('token')
        if not token:
            return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            link = PartnerOnboardingLink.objects.get(
                token=token,
                is_active=True,
                expires_at__gte=timezone.now()
            )
            return Response({
                'valid': True,
                'expires_at': link.expires_at,
                'created_by': link.created_by.username,
                'notes': link.notes
            })
        except PartnerOnboardingLink.DoesNotExist:
            return Response({'valid': False}, status=status.HTTP_200_OK)

    
    @action(detail=False, methods=['get'])
    def my_profile(self, request):
        # Check if the user is an admin
        user = request.user
        if user.is_staff:  # Assuming 'is_staff' means the user is an admin
            # Admin users can see all partner profiles
            partners = PartnerProfile.objects.all()
            serializer = PartnerProfileSerializer(partners, many=True)
            return Response(serializer.data)
        else:
            # If not an admin, return only the current user's profile
            try:
                partner = PartnerProfile.objects.get(user=user)
                serializer = self.get_serializer(partner)
                return Response(serializer.data)
            except PartnerProfile.DoesNotExist:
                return Response(
                    {'error': 'Partner profile not found for this user'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
    
    @action(detail=False, methods=['get'])
    def dashboard(self, request, pk=None):
        """Get dashboard data for the authenticated partner or all partners if admin"""
        try:
            user = request.user

            from referrals_management.models import Referral
            from payouts.models import Earnings

            if user.is_staff:  # Admin view: all partners
                partners = PartnerProfile.objects.all()
                dashboard_data = []

                for partner in partners:
                    referrals = Referral.objects.filter(partner=partner).select_related('product')
                    earnings = Earnings.objects.filter(partner=partner)

                    referral_status_counts = referrals.values('status').annotate(
                        count=Count('id'),
                        total_commission=Sum('actual_commission')
                    )

                    earnings_summary = earnings.aggregate(
                        total=Sum('amount', filter=~Q(status='cancelled')),
                        available=Sum('amount', filter=Q(status='available')),
                        pending=Sum('amount', filter=Q(status='pending'))
                    )

                    dashboard_data.append({
                        'partner': PartnerProfileLiteSerializer(partner).data,
                        'metrics': {
                            'total_referrals': referrals.count(),
                            'referral_status_counts': {
                                item['status']: {
                                    'count': item['count'],
                                    'total_commission': item['total_commission'] or 0
                                } 
                                for item in referral_status_counts
                            },
                            'total_earnings': earnings_summary['total'] or 0,
                            'available_earnings': earnings_summary['available'] or 0,
                            'pending_earnings': earnings_summary['pending'] or 0,
                        },
                        'referrals': {
                            'recent': referrals.order_by('-date_submitted')[:5].values(
                                'id', 'client_name', 'status', 'date_submitted',
                                'expected_implementation_date',
                                'potential_commission', 'actual_commission', 'product__name'
                            ),
                            'by_product': referrals.exclude(product__isnull=True).values(
                                'product__name'
                            ).annotate(
                                count=Count('id'),
                                converted=Count('id', filter=Q(status='converted')),
                                total_commission=Sum('actual_commission')
                            ).order_by('-count')
                        },
                        'earnings': {
                            'recent': earnings.order_by('-date')[:5].values(
                                'id', 'amount', 'date', 'source', 'status', 'referral__client_name'
                            ),
                            'by_month': earnings.exclude(status='cancelled').annotate(
                                month=TruncMonth('date')
                            ).values('month').annotate(
                                sum=Sum('amount'),
                                count=Count('id')
                            ).order_by('month')
                        }
                    })

                return Response(dashboard_data)

            else:
                # Partner-specific dashboard
                partner = PartnerProfile.objects.select_related('user').get(user=user)
                referrals = Referral.objects.filter(partner=partner).select_related('product')
                earnings = Earnings.objects.filter(partner=partner)

                referral_status_counts = referrals.values('status').annotate(
                    count=Count('id'),
                    total_commission=Sum('actual_commission')
                )

                earnings_summary = earnings.aggregate(
                    total=Sum('amount', filter=~Q(status='cancelled')),
                    available=Sum('amount', filter=Q(status='available')),
                    pending=Sum('amount', filter=Q(status='pending'))
                )

                dashboard_data = {
                    'partner': PartnerProfileLiteSerializer(partner).data,
                    'metrics': {
                        'total_referrals': referrals.count(),
                        'referral_status_counts': {
                            item['status']: {
                                'count': item['count'],
                                'total_commission': item['total_commission'] or 0
                            } 
                            for item in referral_status_counts
                        },
                        'total_earnings': earnings_summary['total'] or 0,
                        'available_earnings': earnings_summary['available'] or 0,
                        'pending_earnings': earnings_summary['pending'] or 0,
                    },
                    'referrals': {
                        'recent': referrals.order_by('-date_submitted')[:5].values(
                            'id', 'client_name', 'status', 'date_submitted',
                            'expected_implementation_date',
                            'potential_commission', 'actual_commission', 'product__name'
                        ),
                        'by_product': referrals.exclude(product__isnull=True).values(
                            'product__name'
                        ).annotate(
                            count=Count('id'),
                            converted=Count('id', filter=Q(status='converted')),
                            total_commission=Sum('actual_commission')
                        ).order_by('-count')
                    },
                    'earnings': {
                        'recent': earnings.order_by('-date')[:5].values(
                            'id', 'amount', 'date', 'source', 'status', 'referral__client_name'
                        ),
                        'by_month': earnings.exclude(status='cancelled').annotate(
                            month=TruncMonth('date')
                        ).values('month').annotate(
                            sum=Sum('amount'),
                            count=Count('id')
                        ).order_by('month')
                    }
                }

                return Response(dashboard_data)

        except PartnerProfile.DoesNotExist:
            return Response(
                {'error': 'Partner profile not found for this user'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.exception("Failed to fetch dashboard")
            return Response(
                {'error': 'Unable to fetch dashboard data'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


    
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        partner = self.get_object()
        new_status = request.data.get('status')
        
        if new_status not in dict(PartnerProfile.Status.choices).keys():
            return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)
        
        partner.status = new_status
        partner.save()
        serializer = self.get_serializer(partner)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def add_products(self, request, pk=None):
        partner = self.get_object()
        product_ids = request.data.get('product_ids', [])
        
        if not product_ids:
            return Response({'error': 'No product IDs provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Get products and add to partner
        products = Product.objects.filter(id__in=product_ids)
        partner.selected_products.add(*products)
        
        serializer = self.get_serializer(partner)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def remove_products(self, request, pk=None):
        partner = self.get_object()
        product_ids = request.data.get('product_ids', [])
        
        if not product_ids:
            return Response({'error': 'No product IDs provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Get products and remove from partner
        products = Product.objects.filter(id__in=product_ids)
        partner.selected_products.remove(*products)
        
        serializer = self.get_serializer(partner)
        return Response(serializer.data)