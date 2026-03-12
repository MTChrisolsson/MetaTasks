from django.contrib import admin
from .models import StatistikJob, VehicleRecord, AnalyticsReport, VehicleValuation


@admin.register(StatistikJob)
class StatistikJobAdmin(admin.ModelAdmin):
    list_display = ('organization', 'status', 'uploaded_at', 'processed_at')
    list_filter = ('status', 'uploaded_at', 'organization')
    search_fields = ('organization__name',)
    readonly_fields = ('uploaded_at', 'processed_at', 'created_by')
    
    fieldsets = (
        ('Job Information', {
            'fields': ('organization', 'created_by', 'status', 'uploaded_at', 'processed_at')
        }),
        ('Files', {
            'fields': ('inventory_file', 'wayke_file', 'citk_file', 'notes_file')
        }),
        ('Configuration', {
            'fields': ('inventory_sheet', 'citk_sheet', 'photo_min_urls')
        }),
        ('Results', {
            'fields': ('kpis', 'station_stats', 'error_message'),
            'classes': ('collapse',)
        }),
    )
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_staff


@admin.register(VehicleRecord)
class VehicleRecordAdmin(admin.ModelAdmin):
    list_display = ('registration', 'model', 'current_station', 'is_published', 'is_photographed')
    list_filter = ('is_published', 'is_photographed', 'current_station', 'job')
    search_fields = ('registration', 'model')
    readonly_fields = ('created_at',)


@admin.register(AnalyticsReport)
class AnalyticsReportAdmin(admin.ModelAdmin):
    list_display = ('title', 'report_type', 'organization', 'generated_at')
    list_filter = ('report_type', 'generated_at', 'organization')
    search_fields = ('title', 'organization__name')
    readonly_fields = ('generated_at',)


@admin.register(VehicleValuation)
class VehicleValuationAdmin(admin.ModelAdmin):
    list_display = (
        'registration',
        'make',
        'model',
        'year',
        'published_price',
        'estimated_market_value',
        'fairness_assessment',
        'suggested_price',
        'created_at',
    )
    list_filter = ('fairness_assessment', 'year', 'job', 'created_at')
    search_fields = ('registration', 'make', 'model', 'vehicle__registration')
    readonly_fields = ('created_at', 'raw_response')