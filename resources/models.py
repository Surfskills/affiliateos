from django.db import models
from django.conf import settings
from django.utils import timezone

class ResourceCategory(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    
    class Meta:
        verbose_name_plural = "Resource Categories"
        ordering = ['name']
    
    def __str__(self):
        return self.name

class ResourceTag(models.Model):
    name = models.CharField(max_length=50)
    slug = models.SlugField(max_length=50, unique=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name

class Resource(models.Model):
    VISIBILITY_CHOICES = [
        ('public', 'Public'),
        ('private', 'Private'),
        ('partner', 'Partner Only'),
    ]
    
    RESOURCE_TYPE_CHOICES = [
        ('pdf', 'PDF'),
        ('video', 'Video'),
        ('image', 'Image'),
        ('audio', 'Audio'),
        ('template', 'Template'),
    ]
    
    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.ForeignKey(ResourceCategory, on_delete=models.PROTECT, related_name='resources')
    tags = models.ManyToManyField(ResourceTag, blank=True, related_name='resources')
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default='public')
    resource_type = models.CharField(max_length=10, choices=RESOURCE_TYPE_CHOICES)
    thumbnail = models.ImageField(upload_to='resources/thumbnails/', null=True, blank=True)
    file = models.FileField(upload_to='resources/files/')
    file_size = models.PositiveIntegerField(help_text="File size in bytes")
    partners = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='partner_resources')
    upload_date = models.DateTimeField(default=timezone.now)
    update_date = models.DateTimeField(auto_now=True)
    download_count = models.PositiveIntegerField(default=0)
    view_count = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='uploaded_resources')
    
    class Meta:
        ordering = ['-update_date']
    
    def __str__(self):
        return self.title
    
    def save(self, *args, **kwargs):
        if self.file and not self.file_size:
            self.file_size = self.file.size
        super().save(*args, **kwargs)

class ResourceVersion(models.Model):
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='versions')
    version = models.CharField(max_length=20)
    notes = models.TextField()
    file = models.FileField(upload_to='resources/versions/')
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.resource.title} - v{self.version}"