from rest_framework import permissions

class IsOwnerOrStaff(permissions.BasePermission):
    """
    Custom permission to only allow owners of a document to view or edit it,
    or staff members with appropriate permissions.
    """
    
    def has_permission(self, request, view):
        """Check if user is authenticated."""
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        """
        Return True if:
        - User is the document owner
        - User is staff and has view_all_documents permission
        - For unsafe methods, user is staff with appropriate permissions
        """
        # Owner can always view and edit their own documents
        if obj.user == request.user:
            return True
        
        # Staff with view_all_documents permission can view any document
        if request.method in permissions.SAFE_METHODS:
            return request.user.is_staff and request.user.has_perm('documents.view_all_documents')
        
        # For unsafe methods, staff needs additional permissions
        return (
            request.user.is_staff and 
            (request.user.has_perm('documents.change_document') or 
             request.user.has_perm('documents.verify_document'))
        )


class CanVerifyDocument(permissions.BasePermission):
    """
    Permission to check if user can verify documents.
    """
    
    def has_permission(self, request, view):
        """Check if user has permission to verify documents."""
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.is_staff and
            request.user.has_perm('documents.verify_document')
        )