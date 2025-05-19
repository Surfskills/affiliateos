from rest_framework import serializers

from authentication.serializers import UserSerializer
from .models import ActivityLog, SupportTicket, Comment, SupportTicketAttachment

class CommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    
    class Meta:
        model = Comment
        fields = ['id', 'content', 'author', 'created_at']

class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportTicketAttachment
        fields = ['id', 'file', 'uploaded_at']

class SupportTicketSerializer(serializers.ModelSerializer):
    submitted_by = UserSerializer(read_only=True)
    assigned_to = UserSerializer(read_only=True)
    comments = CommentSerializer(many=True, read_only=True)
    attachments = AttachmentSerializer(many=True, read_only=True)
    
    class Meta:
        model = SupportTicket
        fields = '__all__'

class CreateSupportTicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportTicket
        fields = ['affiliate_id', 'name', 'email', 'issue_category', 'priority',
                  'subject', 'description', 'payment_related', 'marketing_materials',
                  'commission_dispute', 'technical_issue', 'affected_customers']

class UpdateSupportTicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportTicket
        fields = ['status', 'assigned_to', 'priority']

class ActivityLogSerializer(serializers.ModelSerializer):
    performed_by = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = ['id', 'ticket', 'activity_type', 'description', 'performed_by', 'created_at', 'metadata']

    def get_performed_by(self, obj):
        return {
            'id': obj.performed_by.id,
            'name': obj.performed_by.get_full_name() or obj.performed_by.username,
            'email': obj.performed_by.email,
            'isAdmin': obj.performed_by.is_staff
        }