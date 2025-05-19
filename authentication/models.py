from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """Manager for custom user model with email instead of username."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError(_('The email must be set'))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('user_type', 'admin')

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))

        return self._create_user(email, password, **extra_fields)

    def create_support_agent(self, email, password=None, **extra_fields):
        """Creates a support agent user with specific admin privileges."""
        extra_fields.setdefault('is_staff', True)  # Access to admin panel
        extra_fields.setdefault('is_superuser', False)  # Not full superuser
        extra_fields.setdefault('user_type', 'support_agent')
        
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Custom user model using email as unique identifier and only requiring email/password."""

    USER_TYPE_CHOICES = (
        ('admin', 'Admin'),
        ('partner', 'Partner'),
        ('support_agent', 'Support Agent'),
    )

    username = None  # Remove username
    email = models.EmailField(_('email address'), unique=True)
    user_type = models.CharField(max_length=15, choices=USER_TYPE_CHOICES, default='partner')

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []  # Email & password only

    def __str__(self):
        return self.email
        
    @property
    def is_support_agent(self):
        """Helper method to check if user is a support agent."""
        return self.user_type == 'support_agent'

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'