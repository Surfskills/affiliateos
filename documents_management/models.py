from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _

class Document(models.Model):
    """Model for managing document uploads and their status."""
    
    class DocumentType(models.TextChoices):
        PDF = 'pdf', _('PDF')
        IMAGE = 'image', _('Image')
        OTHER = 'other', _('Other')
    
    class DocumentStatus(models.TextChoices):
        VERIFIED = 'verified', _('Verified')
        PENDING = 'pending', _('Pending')
        MISSING = 'missing', _('Missing')
        REQUIRED = 'required', _('Required')
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='documents',
        help_text=_('User who owns this document')
    )
    name = models.CharField(
        max_length=255,
        help_text=_('Document name')
    )
    description = models.TextField(
        blank=True,
        null=True,
        help_text=_('Additional details about this document')
    )
    document_type = models.CharField(
        max_length=10,
        choices=DocumentType.choices,
        default=DocumentType.PDF,
        help_text=_('Type of document')
    )
    status = models.CharField(
        max_length=10,
        choices=DocumentStatus.choices,
        default=DocumentStatus.REQUIRED,
        help_text=_('Current status of the document')
    )
    file = models.FileField(
        upload_to='documents/%Y/%m/%d/',
        blank=True,
        null=True,
        help_text=_('Uploaded document file')
    )
    file_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text=_('Original file name')
    )
    content_type = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text=_('File MIME type')
    )
    file_size = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text=_('File size in bytes')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text=_('When this document was first created')
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text=_('When this document was last updated')
    )
    verification_date = models.DateTimeField(
        blank=True,
        null=True,
        help_text=_('When this document was verified')
    )
    verification_notes = models.TextField(
        blank=True,
        null=True,
        help_text=_('Notes from the verification process')
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_documents',
        help_text=_('Staff member who verified this document')
    )
    
    class Meta:
        verbose_name = _('Document')
        verbose_name_plural = _('Documents')
        ordering = ['-updated_at']
        permissions = [
            ('verify_document', 'Can verify document status'),
            ('view_all_documents', 'Can view all user documents'),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"
    
    def save(self, *args, **kwargs):
        """Override save to update file information when file is provided."""
        if self.file and not self.file_name:
            self.file_name = self.file.name
            
        if self.file and not self.content_type and hasattr(self.file, 'content_type'):
            self.content_type = self.file.content_type
            
        if self.file and not self.file_size and hasattr(self.file, 'size'):
            self.file_size = self.file.size
            
        super().save(*args, **kwargs)


class DocumentRequirement(models.Model):
    """Model for defining document requirements and specifications."""
    name = models.CharField(
        max_length=255,
        help_text=_('Requirement name')
    )
    document_type = models.CharField(
        max_length=10,
        choices=Document.DocumentType.choices,
        default=Document.DocumentType.PDF,
        help_text=_('Type of document required')
    )
    is_required = models.BooleanField(
        default=True,
        help_text=_('Whether this document is mandatory')
    )
    description = models.TextField(
        blank=True,
        null=True,
        help_text=_('Additional details about the requirement')
    )
    max_file_size = models.PositiveIntegerField(
        default=5242880,  # 5MB default
        help_text=_('Maximum file size in bytes')
    )
    allowed_extensions = models.CharField(
        max_length=255,
        default=".pdf,.jpg,.jpeg,.png",
        help_text=_('Comma-separated list of allowed file extensions')
    )
    expiration_period_days = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text=_('Number of days until document is considered expired (null if no expiration)')
    )
    active = models.BooleanField(
        default=True,
        help_text=_('Whether this requirement is currently active')
    )
    
    class Meta:
        verbose_name = _('Document Requirement')
        verbose_name_plural = _('Document Requirements')
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({'Required' if self.is_required else 'Optional'})"