# # services/dashboard.py
# from django.db.models import Sum, Count


# class DashboardService:
#     @staticmethod
#     def get_partner_dashboard(partner):
#         from referrals.models import Referral
#         from payouts.models import Earnings, Payout
        
#         # Recent referrals
#         recent_referrals = Referral.objects.filter(
#             user=partner.user
#         ).order_by('-date_submitted')[:5]
        
#         # Earnings breakdown
#         earnings = Earnings.objects.filter(
#             partner=partner
#         ).aggregate(
#             total=Sum('amount'),
#             available=Sum('amount', filter=models.Q(status='available')),
#             paid=Sum('amount', filter=models.Q(status='paid'))
#         )
        
#         # Payout history
#         payouts = Payout.objects.filter(
#             partner=partner
#         ).order_by('-request_date')[:5]
        
#         # Conversion rate
#         referral_stats = Referral.objects.filter(
#             user=partner.user
#         ).aggregate(
#             total=Count('id'),
#             converted=Count('id', filter=models.Q(status='converted'))
#         )
        
#         conversion_rate = (
#             (referral_stats['converted'] / referral_stats['total'] * 100 
#             if referral_stats['total'] > 0 else 0
#         )
        
#         return {
#             'recent_referrals': recent_referrals,
#             'earnings': earnings,
#             'payouts': payouts,
#             'conversion_rate': conversion_rate,
#             'referral_stats': referral_stats
#         }

#     @staticmethod
#     def get_admin_dashboard():
#         from partner.models import PartnerProfile
#         from referrals.models import Referral
#         from payouts.models import Payout, Earnings
        
#         # Partner stats
#         partner_stats = PartnerProfile.objects.aggregate(
#             total=Count('id'),
#             active=Count('id', filter=models.Q(status='active'))
#         )
        
#         # Referral stats
#         referral_stats = Referral.objects.aggregate(
#             total=Count('id'),
#             converted=Count('id', filter=models.Q(status='converted')),
#             potential_revenue=Sum('potential_commission'),
#             actual_revenue=Sum('actual_commission')
#         )
        
#         # Payout stats
#         payout_stats = Payout.objects.aggregate(
#             total=Sum('amount'),
#             pending=Sum('amount', filter=models.Q(status='pending')),
#             completed=Sum('amount', filter=models.Q(status='completed'))
#         )
        
#         # Monthly trends
#         months = []
#         for i in range(5, -1, -1):  # Last 6 months
#             month = timezone.now() - timedelta(days=30*i)
#             month_start = month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
#             next_month = (month_start + timedelta(days=32)).replace(day=1)
            
#             monthly_data = {
#                 'month': month.strftime('%b %Y'),
#                 'referrals': Referral.objects.filter(
#                     date_submitted__gte=month_start,
#                     date_submitted__lt=next_month
#                 ).count(),
#                 'converted': Referral.objects.filter(
#                     status='converted',
#                     date_submitted__gte=month_start,
#                     date_submitted__lt=next_month
#                 ).count(),
#                 'payouts': Payout.objects.filter(
#                     request_date__gte=month_start,
#                     request_date__lt=next_month
#                 ).aggregate(total=Sum('amount'))['total'] or 0
#             }
#             months.append(monthly_data)
        
#         return {
#             'partner_stats': partner_stats,
#             'referral_stats': referral_stats,
#             'payout_stats': payout_stats,
#             'monthly_trends': months
#         }