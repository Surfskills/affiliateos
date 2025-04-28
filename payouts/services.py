
from django.utils import timezone

class PaymentProcessor:
    @staticmethod
    def process_payment(payout):
        """
        Start the payment processing
        """
        payout.status = payout.Status.PROCESSING
        payout.save()
        
        # Mark related earnings as processing
        for payout_ref in payout.referrals.all():
            if hasattr(payout_ref.referral, 'earning'):
                earning = payout_ref.referral.earning
                earning.mark_as_processing(payout)
                
        return payout
    
    @staticmethod
    def complete_payment(payout, transaction_id=None):
        """
        Mark payment as completed
        """
        payout.status = payout.Status.COMPLETED
        payout.processed_date = timezone.now()
        if transaction_id:
            payout.transaction_id = transaction_id
        payout.save()
        
        # Mark related earnings as paid
        for payout_ref in payout.referrals.all():
            if hasattr(payout_ref.referral, 'earning'):
                earning = payout_ref.referral.earning
                earning.mark_as_paid()
                
        return payout
    
    @staticmethod
    def fail_payment(payout, error_message):
        """
        Mark payment as failed
        """
        payout.status = payout.Status.FAILED
        payout.note = f"{payout.note or ''}\nError: {error_message}"
        payout.save()
        
        # Reset earnings status to available
        for payout_ref in payout.referrals.all():
            if hasattr(payout_ref.referral, 'earning'):
                earning = payout_ref.referral.earning
                earning.status = 'available'
                earning.payout = None
                earning.save()
                
        return payout