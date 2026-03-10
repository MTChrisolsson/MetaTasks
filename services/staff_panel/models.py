from django.db import models
from django.conf import settings
from core.models import Organization
import uuid

class Integration(models.Model):
    """Model to store organization's integration configurations"""
    INTEGRATION_TYPES = [
        ('slack', 'Slack'),
        ('teams', 'Microsoft Teams'),
        ('google', 'Google Workspace'),
        ('github', 'GitHub'),
        ('jira', 'Jira'),
        ('zapier', 'Zapier'),
        ('webhook', 'Custom Webhook'),
        ('blocket', 'Blocket'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('error', 'Error'),
        ('pending', 'Pending Configuration'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='integrations')
    integration_type = models.CharField(max_length=50, choices=INTEGRATION_TYPES)
    name = models.CharField(max_length=200, help_text="Custom name for this integration")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Configuration
    config = models.JSONField(default=dict, help_text="Integration-specific configuration")
    webhook_url = models.URLField(blank=True, help_text="Webhook URL for receiving events")
    api_key = models.CharField(max_length=500, blank=True, help_text="Encrypted API key")
    
    # Settings
    is_enabled = models.BooleanField(default=True)
    send_notifications = models.BooleanField(default=True)
    
    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    last_sync = models.DateTimeField(null=True, blank=True)
    sync_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    
    class Meta:
        unique_together = ['organization', 'integration_type', 'name']
        ordering = ['integration_type', 'name']
    
    def __str__(self):
        return f"{self.organization.name} - {self.get_integration_type_display()}: {self.name}"


class IntegrationLog(models.Model):
    """Log of integration activities"""
    LOG_LEVELS = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('success', 'Success'),
    ]
    
    ACTION_TYPES = [
        ('sync', 'Sync'),
        ('send', 'Send'),
        ('receive', 'Receive'),
        ('configure', 'Configure'),
        ('test', 'Test'),
        ('error', 'Error'),
    ]
    
    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name='logs')
    level = models.CharField(max_length=10, choices=LOG_LEVELS)
    action = models.CharField(max_length=20, choices=ACTION_TYPES)
    message = models.TextField()
    details = models.JSONField(default=dict)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.integration.name} - {self.action} ({self.level})"
