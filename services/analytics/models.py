from django.db import models
from core.models import Organization, UserProfile

class StatistikJob(models.Model):
    """Track statistik processing jobs"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='statistik_jobs')
    created_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    # File references
    inventory_file = models.FileField(upload_to='analytics/inventory/%Y/%m/')
    wayke_file = models.FileField(upload_to='analytics/wayke/%Y/%m/')
    citk_file = models.FileField(upload_to='analytics/citk/%Y/%m/')
    notes_file = models.FileField(upload_to='analytics/notes/%Y/%m/', null=True, blank=True)
    
    # Configuration
    inventory_sheet = models.CharField(max_length=100, default='toyota lager')
    citk_sheet = models.CharField(max_length=100, default='Sheet1')
    photo_min_urls = models.IntegerField(default=1)
    
    # Results (stored as JSON)
    kpis = models.JSONField(null=True, blank=True)
    station_stats = models.JSONField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-uploaded_at']
        
    def __str__(self):
        return f"{self.organization.name} - {self.uploaded_at}"


class VehicleRecord(models.Model):
    """Individual vehicle record from statistik processing"""
    job = models.ForeignKey(StatistikJob, on_delete=models.CASCADE, related_name='vehicle_records')
    
    registration = models.CharField(max_length=50)
    model = models.CharField(max_length=200)
    status = models.IntegerField()
    current_station = models.CharField(max_length=100)
    days_in_stock = models.IntegerField(null=True, blank=True)
    is_published = models.BooleanField(default=False)
    is_photographed = models.BooleanField(default=False)
    photo_count = models.IntegerField(default=0)
    needs_photos = models.BooleanField(default=False)
    missing_citk = models.BooleanField(default=False)
    is_sold = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['job', 'registration']),
            models.Index(fields=['job', 'current_station']),
        ]


class AnalyticsReport(models.Model):
    """Generated analytics reports"""
    REPORT_TYPE_CHOICES = [
        ('daily', 'Daily Report'),
        ('weekly', 'Weekly Report'),
        ('custom', 'Custom Report'),
    ]
    
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='analytics_reports')
    job = models.ForeignKey(StatistikJob, on_delete=models.CASCADE, related_name='reports')
    
    report_type = models.CharField(max_length=20, choices=REPORT_TYPE_CHOICES)
    title = models.CharField(max_length=255)
    generated_at = models.DateTimeField(auto_now_add=True)
    
    # File exports
    excel_file = models.FileField(upload_to='analytics/exports/%Y/%m/', null=True, blank=True)
    pdf_file = models.FileField(upload_to='analytics/exports/%Y/%m/', null=True, blank=True)
    
    class Meta:
        ordering = ['-generated_at']