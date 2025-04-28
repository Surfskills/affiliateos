# api/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from partner.models import PartnerProfile
from payouts.exceptions import PaymentProcessingError
from services.dashboard import DashboardService
import logging
from django.utils import timezone
from django.db import transaction
from rest_framework import status



logger = logging.getLogger(__name__)

class DashboardAPI(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        if request.user.is_staff:
            data = DashboardService.get_admin_dashboard()
        else:
            try:
                partner = request.user.partner_profile
                data = DashboardService.get_partner_dashboard(partner)
            except PartnerProfile.DoesNotExist:
                return Response(
                    {'error': 'Partner profile not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        
        return Response(data)
    


class PaymentProcessor:
    @classmethod
    def process_payment(cls, payout):
        if payout.status != payout.Status.PENDING:
            raise PaymentProcessingError("Only pending payouts can be processed")
        
        processor = cls._get_processor(payout.payment_method)
        return processor(payout)
    
    @classmethod
    def complete_payment(cls, payout, transaction_id=None):
        if payout.status != payout.Status.PROCESSING:
            raise PaymentProcessingError("Only processing payouts can be completed")
        
        with transaction.atomic():
            # Update payout status
            payout.status = payout.Status.COMPLETED
            payout.processed_date = timezone.now()
            
            if transaction_id:
                payout.payment_details['transaction_id'] = transaction_id
                
            payout.save()
            
            # Mark earnings as paid
            payout.partner.earnings.filter(
                status='processing'
            ).update(status='paid')
            
            return True
    
    @classmethod
    def fail_payment(cls, payout, error_message):
        payout.status = payout.Status.FAILED
        payout.payment_details['error'] = error_message
        payout.payment_details['failed_at'] = timezone.now().isoformat()
        payout.save()
        
        # Return earnings to available status
        payout.partner.earnings.filter(
            status='processing'
        ).update(status='available')
        
        return True
    
    @classmethod
    def _get_processor(cls, payment_method):
        return {
            'bank': cls._process_bank_transfer,
            'paypal': cls._process_paypal,
            'stripe': cls._process_stripe,
            'mpesa': cls._process_mpesa,
            'crypto': cls._process_crypto,
        }.get(payment_method, cls._process_bank_transfer)
    
    @staticmethod
    def _process_bank_transfer(payout):
        try:
            payout.payment_details.update({
                'processing_id': f"BT-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                'initiated_at': timezone.now().isoformat()
            })
            payout.status = payout.Status.PROCESSING
            payout.save()
            return True
        except Exception as e:
            logger.error(f"Bank transfer processing failed: {str(e)}")
            raise PaymentProcessingError("Bank transfer processing failed")
    
    @staticmethod
    def _process_mpesa(payout):
        if 'phone_number' not in payout.payment_details:
            raise PaymentProcessingError("M-Pesa requires a phone number")
        
        try:
            # In production, integrate with actual M-Pesa API
            payout.payment_details.update({
                'mpesa_reference': f"MP{timezone.now().strftime('%Y%m%d%H%M%S')}",
                'initiated_at': timezone.now().isoformat()
            })
            payout.status = payout.Status.PROCESSING
            payout.save()
            return True
        except Exception as e:
            logger.error(f"M-Pesa processing failed: {str(e)}")
            raise PaymentProcessingError("M-Pesa processing failed")

    # Similar methods for other payment processors...