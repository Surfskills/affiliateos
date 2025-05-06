from rest_framework import serializers
from .models import Document, DocumentRequirement

from rest_framework import serializers
from django.conf import settings
from .models import Document, DocumentRequirement
import logging

logger = logging.getLogger(__name__)


from rest_framework import serializers
from django.conf import settings
from .models import Document, DocumentRequirement
import logging

logger = logging.getLogger(__name__)


class DocumentSerializer(serializers.ModelSerializer):
    """Serializer for Document model with file upload handling."""
    file_url = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    document_type_display = serializers.CharField(source='get_document_type_display', read_only=True)

    class Meta:
        model = Document
        fields = [
            'id', 
            'name', 
            'description', 
            'document_type',
            'document_type_display',
            'status', 
            'status_display',
            'file', 
            'file_name',
            'file_url',
            'content_type',
            'file_size',
            'created_at',
            'updated_at',
            'verification_date',
            'verification_notes'
        ]
        read_only_fields = [
            'id', 
            'file_name', 
            'content_type', 
            'file_size', 
            'created_at', 
            'updated_at',
            'verification_date',
            'verification_notes',
            'status_display',
            'document_type_display'
        ]
    
    def get_file_url(self, obj):
        """Get the URL for the file if it exists."""
        if obj.file:
            request = self.context.get('request')
            if request is not None:
                return request.build_absolute_uri(obj.file.url)
        return None

    def validate_file(self, value):
        """Validate uploaded file size and type."""
        if not value:
            return value

        document_type = self.initial_data.get('document_type', '')
        name = self.initial_data.get('name', '')
        logger.debug(f"Validating file upload: name={name}, document_type={document_type}, size={value.size}")

        # Find matching requirement
        requirement = None
        try:
            requirement = DocumentRequirement.objects.filter(
                name__iexact=name,
                active=True
            ).first() or DocumentRequirement.objects.filter(
                document_type=document_type,
                active=True
            ).first()
            
            if requirement:
                logger.debug(f"Found matching requirement: {requirement.name} with max_file_size={requirement.max_file_size}")
        except Exception as e:
            logger.warning(f"Error while fetching DocumentRequirement: {e}")

        # Set reasonable minimum file size limit (5MB default)
        DEFAULT_MAX_SIZE = 5 * 1024 * 1024  # 5MB default
        
        # Use specific requirement size limit or default
        if requirement and requirement.max_file_size and requirement.max_file_size > 100000:  # Sanity check: at least 100KB
            # Use the requirement's size limit
            max_size = requirement.max_file_size  # Already in bytes
            logger.debug(f"Using requirement max size: {max_size} bytes ({max_size/(1024*1024):.1f} MB)")
        else:
            # Fallback to global or default size limit
            max_size = getattr(settings, 'MAX_UPLOAD_SIZE', DEFAULT_MAX_SIZE)
            logger.debug(f"Using fallback max size: {max_size} bytes ({max_size/(1024*1024):.1f} MB)")
        
        # Ensure we never have a zero or tiny max size
        if max_size < 1024 * 1024:  # If less than 1MB, use default
            logger.warning(f"Max size {max_size} is too small, using default 5MB instead")
            max_size = DEFAULT_MAX_SIZE
            
        # Now check the file size
        if value.size > max_size:
            max_size_mb = max_size / (1024 * 1024)
            logger.warning(f"File size {value.size} exceeds max {max_size}")
            raise serializers.ValidationError(
                f"File is too large. Maximum size is {max_size_mb:.1f} MB."
            )

        # Validate extension if applicable
        if requirement and requirement.allowed_extensions:
            allowed_exts = [ext.strip().lower() for ext in requirement.allowed_extensions.split(',') if ext.strip()]
            file_ext = f".{value.name.split('.')[-1].lower()}" if '.' in value.name else ''
            if allowed_exts and file_ext and file_ext not in allowed_exts:
                logger.warning(f"Invalid file extension: {file_ext}. Allowed: {allowed_exts}")
                raise serializers.ValidationError(
                    f"Invalid file extension. Allowed extensions are: {requirement.allowed_extensions}"
                )

        return value
class DocumentRequirementSerializer(serializers.ModelSerializer):
    """Serializer for DocumentRequirement model."""
    document_type_display = serializers.CharField(source='get_document_type_display', read_only=True)
    
    class Meta:
        model = DocumentRequirement
        fields = [
            'id',
            'name',
            'document_type',
            'document_type_display',
            'is_required',
            'description',
            'max_file_size',
            'allowed_extensions',
            'expiration_period_days',
            'active'
        ]