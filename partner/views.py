from decimal import Decimal
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Count, Sum, Case, When, F, IntegerField
from django.utils import timezone
from datetime import timedelta
from rest_framework import viewsets, status, permissions 
import secrets
from django.db.models import Prefetch
from django.utils.text import slugify
from django.db.models.functions import TruncMonth
from rest_framework.decorators import api_view
import json
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.db.models import Count, Sum, Avg, F, Q, ExpressionWrapper, fields
from django.utils import timezone
from documents_management.models import Document
from partner.dashboard_metrics import DashboardMetrics
from payouts.models import Earnings, Payout
from referrals_management.models import Referral
from resources.models import Resource
from .models import PartnerOnboardingLink, PartnerProfile, Product, Testimonial
from .serializers import PartnerOnboardingLinkSerializer,  PartnerProfileSerializer, PartnerDetailSerializer, PartnerProfileUpdateSerializer, ProductSerializer, TestimonialSerializer
from rest_framework.permissions import IsAuthenticated
from rest_framework.permissions import IsAuthenticatedOrReadOnly, IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow owners of a profile to edit it.
    """
    def has_object_permission(self, request, view, obj):
        # Allow safe methods for all users (GET, OPTIONS, HEAD)
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Check if the object is related to the user's PartnerProfile
        if isinstance(obj, Product):
            return obj in request.user.partner_profile.selected_products.all()
        
        if isinstance(obj, Testimonial):
            return obj in request.user.partner_profile.testimonials.all()

        # Default check if the object is owned by the authenticated user
        return obj.user == request.user


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """
    A viewset for viewing products.
    """
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]  # Allow anyone to read, authenticated users to write
    
    def get_queryset(self):
        # Retrieve the products that are associated with the authenticated user's PartnerProfile
        partner_profile = self.request.user.partner_profile  # Access PartnerProfile via user
        return partner_profile.selected_products.all()  # Access the products linked to the PartnerProfile
    
    def get_permissions(self):
        # For update, partial update, and destroy actions, check if the user is the owner
        if self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsOwnerOrReadOnly()]
        return super().get_permissions()




class TestimonialViewSet(viewsets.ModelViewSet):
    """
    A viewset for managing testimonials.
    """
    queryset = Testimonial.objects.all()
    serializer_class = TestimonialSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_permissions(self):
        # For update, partial update, and delete actions, check if the user is the owner
        if self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsOwnerOrReadOnly()]
        elif self.action in ['approve', 'reject']:
            return [IsAuthenticated()]  # Optional: Restrict to admin here
        return super().get_permissions()

    def create(self, request, *args, **kwargs):
        # Validate the input data based on testimonial type
        testimonial_type = request.data.get('type', 'text')

        if testimonial_type == 'text' and not request.data.get('content'):
            return Response({'error': 'Content is required for text testimonials'}, status=status.HTTP_400_BAD_REQUEST)

        if testimonial_type == 'image' and not request.FILES.get('image'):
            return Response({'error': 'Image file is required for image testimonials'}, status=status.HTTP_400_BAD_REQUEST)

        if testimonial_type == 'video' and not request.FILES.get('video'):
            return Response({'error': 'Video file is required for video testimonials'}, status=status.HTTP_400_BAD_REQUEST)

        return super().create(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        testimonial = self.get_object()
        if testimonial.status == Testimonial.Status.APPROVED:
            return Response({'detail': 'Already approved'}, status=status.HTTP_400_BAD_REQUEST)
        testimonial.status = Testimonial.Status.APPROVED
        testimonial.save()
        return Response({'status': 'approved'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        testimonial = self.get_object()
        if testimonial.status == Testimonial.Status.REJECTED:
            return Response({'detail': 'Already rejected'}, status=status.HTTP_400_BAD_REQUEST)
        testimonial.status = Testimonial.Status.REJECTED
        testimonial.save()
        return Response({'status': 'rejected'}, status=status.HTTP_200_OK)




class PartnerViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = PartnerProfile.objects.all()
    serializer_class = PartnerProfileSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticatedOrReadOnly]  


    def perform_create(self, serializer):
        request = self.request
        print(f"Request data: {request.data}")

        # Ensure a unique slug
        name_for_slug = request.data.get('name') or request.user.username
        slug = self._generate_unique_slug(name_for_slug)

        try:
            partner_profile = serializer.save(user=request.user, slug=slug)
            self._handle_selected_products(partner_profile)
            self._handle_testimonials(partner_profile)
        except Exception as e:
            import traceback
            print(f"Error in perform_create: {str(e)}")
            print(traceback.format_exc())
            raise

    
    @action(detail=False, methods=['get'], url_path='my_profile', permission_classes=[IsAuthenticated])
    def my_profile(self, request):
        """
        Returns the partner profile for the currently authenticated user.
        """
        try:
            # FIXED: Use select_related and prefetch_related for better performance
            profile = PartnerProfile.objects.select_related('user').prefetch_related(
                'selected_products', 
                'testimonials'
            ).get(user=request.user)
        except PartnerProfile.DoesNotExist:
            return Response({"error": "Partner not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(profile)
        return Response(serializer.data)

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PartnerDetailSerializer
        return super().get_serializer_class()
    
    from django.db.models import Count, Case, When, IntegerField, Sum, F

    def get_queryset(self):
        """
        Customize the queryset to include calculated fields needed for the frontend,
        and apply user-based filtering for access control.
        """
        user = self.request.user

        # Optimized queryset with proper prefetching
        queryset = PartnerProfile.objects.select_related('user').prefetch_related(
            'user__referrals',
            Prefetch('selected_products', queryset=Product.objects.all()),
            'testimonials'
        ).annotate(
            total_referrals_count=Count('user__referrals'),
            converted_referrals_count=Count(
                Case(
                    When(user__referrals__status='converted', then=1),
                    output_field=IntegerField()
                )
            )
        )

        # Add calculated fields for earnings if the model supports it
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

        # Apply user-based access control
        if not (user.is_staff or user.is_superuser):
            queryset = queryset.filter(user=user)

        return queryset


    def _handle_selected_products(self, partner_profile):
        """
        Handle the creation or update of products associated with a partner profile.
        """
        # Try both snake_case and camelCase field names
        selected_products_data = self.request.data.get('selected_products')
        if not selected_products_data:
            selected_products_data = self.request.data.get('selectedProducts')
        
        if selected_products_data:
            import json
            if isinstance(selected_products_data, str):
                try:
                    selected_products_data = json.loads(selected_products_data)
                except json.JSONDecodeError:
                    print("Error parsing JSON string")
                    selected_products_data = []
            
            # Clear existing products and create new associations
            partner_profile.selected_products.clear()
            
            # Process each product
            products = []
            for product_data in selected_products_data:
                product_id = product_data.get("id")
                if product_id:
                    try:
                        # Try to get existing product
                        product = Product.objects.get(id=product_id)
                        # Update product fields with the incoming data
                        for field in ['title', 'description', 'commission', 'price', 'cost', 
                                    'category', 'type', 'features', 'exclusive']:
                            if field in product_data:
                                setattr(product, field, product_data[field])
                        product.save()
                    except Product.DoesNotExist:
                        # If it doesn't exist, create it with all fields
                        product = Product.objects.create(
                            id=product_id,
                            title=product_data.get("title", ""),
                            name=product_data.get("name", product_data.get("title", "")),  # Fallback to title if name not provided
                            description=product_data.get("description", ""),
                            commission=product_data.get("commission", ""),
                            price=product_data.get("price", ""),
                            cost=product_data.get("cost", ""),
                            category=product_data.get("category", ""),
                            type=product_data.get("type", ""),
                            features=product_data.get("features", []),
                            exclusive=product_data.get("exclusive", False),
                            delivery_time=product_data.get("deliveryTime", ""),
                            support_duration=product_data.get("supportDuration", ""),
                            svg_image=product_data.get("svgImage", None),
                            process_link=product_data.get("processLink", None),
                            booking_path=product_data.get("bookingPath", None)
                        )
                    products.append(product)
            
            # Print debug info
            print(f"Associated {len(products)} products with partner profile {partner_profile.id}")
            
            # Associate products with partner profile
            partner_profile.selected_products.set(products)
            
    def _handle_testimonials(self, partner_profile):
        """
        Handle the creation or update of testimonials associated with a partner profile.
        """
        # Try both snake_case and camelCase field names
        testimonials_data = self.request.data.get('testimonials')
        if not testimonials_data:
            testimonials_data = self.request.data.get('testimonials')
        
        if isinstance(testimonials_data, str):
            try:
                testimonials_data = json.loads(testimonials_data)
            except json.JSONDecodeError:
                print("Error parsing JSON string for testimonials")
                testimonials_data = []
        
        if not isinstance(testimonials_data, list):
            print("Testimonials data is not a list")
            return
        
        # Clear existing testimonials and create new ones
        partner_profile.testimonials.clear()
        
        # Process each testimonial
        for testimonial_data in testimonials_data:
            testimonial_type = testimonial_data.get("type")
            if not testimonial_type:
                continue
                
            # Handle text testimonials
            if testimonial_type == "text":
                testimonial = Testimonial.objects.create(
                    type="text",
                    content=testimonial_data.get("content", ""),
                    author=testimonial_data.get("author", ""),
                    role=testimonial_data.get("role", ""),
                    company=testimonial_data.get("company", ""),
                    is_approved=testimonial_data.get("isApproved", False)
                )
                partner_profile.testimonials.add(testimonial)
            
            # Handle image testimonials
            elif testimonial_type == "image":
                # Get image file from request.FILES if available
                image_file = self.request.FILES.get('testimonial_image')
                if not image_file:
                    continue
                    
                testimonial = Testimonial.objects.create(
                    type="image",
                    author=testimonial_data.get("author", ""),
                    role=testimonial_data.get("role", ""),
                    company=testimonial_data.get("company", ""),
                    image=image_file,
                    is_approved=testimonial_data.get("isApproved", False)
                )
                partner_profile.testimonials.add(testimonial)
            
            # Handle video testimonials
            elif testimonial_type == "video":
                # Get video file from request.FILES if available
                video_file = self.request.FILES.get('testimonial_video')
                if not video_file:
                    continue
                    
                testimonial = Testimonial.objects.create(
                    type="video",
                    author=testimonial_data.get("author", ""),
                    role=testimonial_data.get("role", ""),
                    company=testimonial_data.get("company", ""),
                    video=video_file,
                    is_approved=testimonial_data.get("isApproved", False)
                )
                partner_profile.testimonials.add(testimonial)
        
        print(f"Associated {len(testimonials_data)} testimonials with partner profile {partner_profile.id}")
    @action(detail=True, methods=['post'])
    def add_testimonial(self, request, pk=None):
        profile = self.get_object()
        testimonial_type = request.data.get('type', 'text')
        author = request.data.get('author')

        if testimonial_type == 'text':
            content = request.data.get('content')
            if not content or not author:
                return Response({'error': 'Content and author are required for text testimonials'}, status=status.HTTP_400_BAD_REQUEST)
            testimonial = Testimonial.objects.create(
                type='text',
                content=content,
                author=author,
                role=request.data.get('role', ''),
                company=request.data.get('company', '')
            )

        elif testimonial_type == 'image':
            image = request.FILES.get('image')
            if not image or not author:
                return Response({'error': 'Image file and author are required for image testimonials'}, status=status.HTTP_400_BAD_REQUEST)
            testimonial = Testimonial.objects.create(
                type='image',
                image=image,
                author=author,
                role=request.data.get('role', ''),
                company=request.data.get('company', '')
            )

        elif testimonial_type == 'video':
            video = request.FILES.get('video')
            if not video or not author:
                return Response({'error': 'Video file and author are required for video testimonials'}, status=status.HTTP_400_BAD_REQUEST)
            testimonial = Testimonial.objects.create(
                type='video',
                video=video,
                author=author,
                role=request.data.get('role', ''),
                company=request.data.get('company', '')
            )

        else:
            return Response({'error': 'Invalid testimonial type'}, status=status.HTTP_400_BAD_REQUEST)

        profile.testimonials.add(testimonial)
        return Response(TestimonialSerializer(testimonial).data, status=status.HTTP_201_CREATED)
    
    def _generate_unique_slug(self, base_text):
        base_slug = slugify(base_text)
        slug = base_slug
        counter = 1
        while PartnerProfile.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug

    @action(detail=True, methods=['delete'])
    def remove_testimonial(self, request, pk=None):
        profile = self.get_object()
        testimonial_id = request.data.get('testimonial_id')

        if not testimonial_id:
            return Response({'error': 'Testimonial ID is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            testimonial = profile.testimonials.get(id=testimonial_id)
            profile.testimonials.remove(testimonial)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Testimonial.DoesNotExist:
            return Response({'error': 'Testimonial not found'}, status=status.HTTP_404_NOT_FOUND)
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
    
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        print("Raw products:", list(instance.selected_products.all()))
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
@api_view(['GET', 'POST'])
def store_selected_products(request, partner_id=None):
    """
    Endpoint to store and retrieve selected products for partner profiles.
    GET: View selected products for a specific partner (public if allowed, otherwise admin only)
    POST: Only partner owners or admins can modify selected products
    
    Supports both string and UUID partner IDs
    """
    
    # Helper function to check admin status
    def is_admin_user(user):
        return user.is_authenticated and (user.is_staff or user.is_superuser)
    
    # Helper function to get partner profile by ID (handles both string and UUID)
    def get_partner_profile(partner_id):
        try:
            # First try direct lookup (works for both string and UUID if database supports it)
            return PartnerProfile.objects.get(id=partner_id)
        except (PartnerProfile.DoesNotExist, ValueError):
            try:
                # If direct lookup fails, try filtering with exact string match
                return PartnerProfile.objects.filter(id=partner_id).first()
            except Exception:
                return None
    
    # ---------- GET request handling ----------
    if request.method == 'GET':
        if not partner_id:
            if not is_admin_user(request.user):
                return Response(
                    {'error': 'Partner ID is required for non-admin users'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Admin viewing all products
            all_products = Product.objects.filter(partners__isnull=False).distinct()
            serializer = ProductSerializer(all_products, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        partner_profile = get_partner_profile(partner_id)
        if not partner_profile:
            return Response(
                {'error': 'Partner profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )
            
        products = partner_profile.selected_products.all()
        serializer = ProductSerializer(products, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    # ---------- POST request handling ----------
    elif request.method == 'POST':
        if not request.user.is_authenticated:
            return Response(
                {'error': 'Authentication required'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        if not partner_id:
            return Response(
                {'error': 'Partner ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        partner_profile = get_partner_profile(partner_id)
        if not partner_profile:
            return Response(
                {'error': 'Partner profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check permissions: either owner or admin
        if not (str(partner_profile.user.id) == str(request.user.id) or is_admin_user(request.user)):
            return Response(
                {'error': 'You can only modify your own partner profile'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get selected products data from request
        selected_products_data = request.data.get('selected_products', [])
        if not selected_products_data:
            # Try parsing from a JSON string if necessary (from FormData)
            selected_products_str = request.data.get('selectedProducts')
            if selected_products_str:
                try:
                    selected_products_data = json.loads(selected_products_str) if isinstance(selected_products_str, str) else selected_products_str
                except json.JSONDecodeError:
                    return Response(
                        {'error': 'Invalid JSON format for selected products'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
        
        if not isinstance(selected_products_data, list):
            return Response(
                {'error': 'Selected products data must be a list'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Clear existing products and create new associations
        partner_profile.selected_products.clear()
        
        products = []
        for product_data in selected_products_data:
            product_id = product_data.get('id')
            
            if product_id:
                try:
                    product = Product.objects.get(id=product_id)
                    # Update product fields
                    field_mappings = {
                        'delivery_time': 'deliveryTime',
                        'support_duration': 'supportDuration',
                        'svg_image': 'svgImage',
                        'process_link': 'processLink',
                        'booking_path': 'bookingPath'
                    }
                    
                    for field in [
                        'name', 'title', 'description', 'commission', 'price', 'cost',
                        'category', 'delivery_time', 'support_duration', 'svg_image',
                        'process_link', 'exclusive', 'booking_path', 'features', 'type'
                    ]:
                        frontend_field = field_mappings.get(field, field)
                        value = product_data.get(frontend_field)
                        if value is not None:
                            setattr(product, field, value)
                    
                    product.save()
                
                except Product.DoesNotExist:
                    # Create new product
                    product = Product.objects.create(
                        id=product_id,
                        name=product_data.get('name', ''),
                        title=product_data.get('title', ''),
                        description=product_data.get('description', ''),
                        commission=product_data.get('commission', ''),
                        price=product_data.get('price', ''),
                        cost=product_data.get('cost', ''),
                        delivery_time=product_data.get('deliveryTime', ''),
                        support_duration=product_data.get('supportDuration', ''),
                        svg_image=product_data.get('svgImage', None),
                        process_link=product_data.get('processLink', None),
                        exclusive=product_data.get('exclusive', None),
                        booking_path=product_data.get('bookingPath', None),
                        features=product_data.get('features', []),
                        category=product_data.get('category', ''),
                        type=product_data.get('type', '')
                    )
                
                products.append(product)
        
        partner_profile.selected_products.add(*products)
        
        return Response({
            'message': 'Products saved successfully',
            'count': len(products),
            'partner_id': str(partner_profile.id)  # Ensure ID is stringified
        }, status=status.HTTP_200_OK)
    


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

class DashboardViewSet(viewsets.ViewSet):
    """
    API endpoint for dashboard metrics
    """
    permission_classes = [IsAdminUser]  # Only admin users can view dashboard metrics
    
    @action(detail=False, methods=['get'])
    def metrics(self, request):
        """Get all dashboard metrics"""
        metrics = DashboardMetrics.get_all_metrics()
        return Response(metrics)
    
    @action(detail=False, methods=['get'])
    def overview(self, request):
        """Get overview metrics"""
        metrics = DashboardMetrics.get_overview_metrics()
        return Response(metrics)
    
    @action(detail=False, methods=['get'])
    def referrals(self, request):
        """Get referral metrics"""
        metrics = DashboardMetrics.get_referral_metrics()
        return Response(metrics)
    
    @action(detail=False, methods=['get'])
    def partners(self, request):
        """Get partner metrics"""
        metrics = DashboardMetrics.get_partner_metrics()
        return Response(metrics)
    
    @action(detail=False, methods=['get'])
    def earnings(self, request):
        """Get earnings metrics"""
        metrics = DashboardMetrics.get_earnings_metrics()
        return Response(metrics)
    
    @action(detail=False, methods=['get'])
    def payouts(self, request):
        """Get payout metrics"""
        metrics = DashboardMetrics.get_payout_metrics()
        return Response(metrics)
    
    @action(detail=False, methods=['get'])
    def resources(self, request):
        """Get resource metrics"""
        metrics = DashboardMetrics.get_resource_metrics()
        return Response(metrics)
    
    @action(detail=False, methods=['get'])
    def documents(self, request):
        """Get document metrics"""
        metrics = DashboardMetrics.get_document_metrics()
        return Response(metrics)
    
    @action(detail=False, methods=['get'])
    def products(self, request):
        """Get product metrics"""
        metrics = DashboardMetrics.get_product_metrics()
        return Response(metrics)