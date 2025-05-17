from django.db import models

from authentication.models import User






class SupportTicket(models.Model):
    ISSUE_CATEGORIES = (
        ('technical', 'Technical Issue'),
        ('payment', 'Payment/Commission'),
        ('account', 'Account Management'),
        ('marketing', 'Marketing Materials'),
        ('compliance', 'Compliance Question'),
        ('other', 'Other'),
    )

    PRIORITY_LEVELS = (
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    )

    STATUS_CHOICES = (
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    )

    submitted_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='submitted_tickets')
    affiliate_id = models.CharField(max_length=50)
    name = models.CharField(max_length=255)
    email = models.EmailField()
    issue_category = models.CharField(max_length=20, choices=ISSUE_CATEGORIES)
    priority = models.CharField(max_length=20, choices=PRIORITY_LEVELS, default='medium')
    subject = models.CharField(max_length=255)
    description = models.TextField()
    payment_related = models.BooleanField(default=False)
    marketing_materials = models.BooleanField(default=False)
    commission_dispute = models.BooleanField(default=False)
    technical_issue = models.BooleanField(default=False)
    affected_customers = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tickets')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.subject} - {self.get_status_display()}"

class Comment(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Comment by {self.author.email} on {self.ticket.subject}"

class SupportTicketAttachment(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='support_attachments/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Attachment for {self.ticket.subject}"
    

class ActivityLog(models.Model):
    ACTIVITY_TYPES = (
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('comment', 'Comment'),
        ('status_change', 'Status Change'),
        ('priority_change', 'Priority Change'),
        ('assignment', 'Assignment'),
        ('file_upload', 'File Upload'),
    )

    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='activity_logs')
    activity_type = models.CharField(max_length=20, choices=ACTIVITY_TYPES)
    description = models.CharField(max_length=255)
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_activity_type_display()} by {self.performed_by} on {self.ticket}"