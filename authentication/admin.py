from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User

class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ('email', 'user_type', 'first_name', 'last_name', 'is_staff', 'is_active')
    list_filter = ('user_type', 'is_staff', 'is_active')
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal Info'), {'fields': ('first_name', 'last_name')}),
        (_('Permissions'), {'fields': ('user_type', 'is_staff', 'is_active', 'is_superuser',
                                      'groups', 'user_permissions')}),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'user_type', 'is_staff', 'is_active')}
        ),
    )
    
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('email',)
    
    def get_form(self, request, obj=None, **kwargs):
        """
        Customize form based on user type to enforce proper permissions.
        """
        form = super().get_form(request, obj, **kwargs)
        
        # Check if user is support agent
        is_superuser = request.user.is_superuser
        is_support_agent = hasattr(request.user, 'user_type') and request.user.user_type == 'support_agent'
        
        # If the user is a support agent (not superuser), limit what they can edit
        if not is_superuser and is_support_agent:
            # Disable critical permission fields
            for field in ['is_superuser', 'is_staff', 'user_type', 'groups', 'user_permissions']:
                if field in form.base_fields:
                    form.base_fields[field].disabled = True
                    
        return form
    
    def get_queryset(self, request):
        """
        Filter queryset for support agents to see only partner users.
        Admins can see all users.
        """
        qs = super().get_queryset(request)
        
        # Support agents can only see partner users, not other admins or support agents
        if not request.user.is_superuser and hasattr(request.user, 'user_type') and request.user.user_type == 'support_agent':
            return qs.filter(user_type='partner')
            
        return qs
    
    def has_change_permission(self, request, obj=None):
        """Determine if user can change the object."""
        # If this is a support agent
        if not request.user.is_superuser and hasattr(request.user, 'user_type') and request.user.user_type == 'support_agent':
            # If object exists and is not a partner user, deny permission
            if obj and obj.user_type != 'partner':
                return False
        return super().has_change_permission(request, obj)
    
    def has_delete_permission(self, request, obj=None):
        """Determine if user can delete the object."""
        # Support agents can't delete any users
        if not request.user.is_superuser and hasattr(request.user, 'user_type') and request.user.user_type == 'support_agent':
            return False
        return super().has_delete_permission(request, obj)
    
    def save_model(self, request, obj, form, change):
        """
        Override save_model to handle user creation based on user_type.
        This ensures users created through admin interface use the correct methods.
        """
        if not change:  # Only for new users (not editing existing)
            user_type = obj.user_type
            email = obj.email
            first_name = obj.first_name
            last_name = obj.last_name
            
            # Get the password from the form directly
            password = form.cleaned_data.get('password1')
            
            try:
                # Create the user based on user type
                if user_type == 'admin':
                    # For admin users, use create_superuser
                    user = User.objects.create_superuser(
                        email=email,
                        password=password,
                        first_name=first_name,
                        last_name=last_name
                    )
                elif user_type == 'support_agent':
                    # For support agents, use specialized method
                    user = User.objects.create_support_agent(
                        email=email,
                        password=password,
                        first_name=first_name,
                        last_name=last_name
                    )
                else:
                    # For partners, use create_user
                    user = User.objects.create_user(
                        email=email,
                        password=password,
                        first_name=first_name,
                        last_name=last_name,
                        user_type=user_type
                    )
                
                # Copy attributes from new user to the form's object
                # This ensures the admin form works correctly
                for key, value in user.__dict__.items():
                    if key != '_state':
                        setattr(obj, key, value)
                
            except Exception as e:
                self.message_user(request, f"Error creating user: {str(e)}", level='ERROR')
                raise
        else:
            # For existing users, use default admin save behavior
            super().save_model(request, obj, form, change)

admin.site.register(User, CustomUserAdmin)