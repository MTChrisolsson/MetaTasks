from django import forms
from django.contrib import admin

from .models import AnalyticsReport, AnalyticsTool, StatistikJob, VehicleRecord, VehicleValuation


class AnalyticsToolAdminForm(forms.ModelForm):
    class Meta:
        model = AnalyticsTool
        fields = '__all__'

    def clean(self):
        cleaned = super().clean()
        # Delegate business validation to the model's clean().
        self.instance.organization = cleaned.get('organization')
        self.instance.action_type = cleaned.get('action_type')
        self.instance.target_path = cleaned.get('target_path') or ''
        self.instance.target_view_name = cleaned.get('target_view_name') or ''
        self.instance.slug = cleaned.get('slug')
        self.instance.name = cleaned.get('name')
        self.instance.icon = cleaned.get('icon')
        self.instance.metadata = cleaned.get('metadata') or {}
        self.instance.open_in_new_tab = cleaned.get('open_in_new_tab')
        self.instance.description = cleaned.get('description') or ''
        self.instance.sort_order = cleaned.get('sort_order')
        self.instance.is_active = cleaned.get('is_active')
        self.instance.full_clean(exclude=['created_by'])
        return cleaned


@admin.register(AnalyticsTool)
class AnalyticsToolAdmin(admin.ModelAdmin):
    form = AnalyticsToolAdminForm
    list_display = (
        'name',
        'organization',
        'action_type',
        'target_view_name',
        'target_path',
        'is_active',
        'sort_order',
    )
    list_filter = ('organization', 'is_active', 'action_type')
    search_fields = ('name', 'slug', 'description', 'organization__name', 'target_view_name', 'target_path')
    readonly_fields = ('created_at', 'updated_at', 'created_by')
    ordering = ('organization__name', 'sort_order', 'name')

    fieldsets = (
        ('Tool Basics', {
            'fields': ('organization', 'created_by', 'name', 'slug', 'description', 'icon', 'sort_order', 'is_active')
        }),
        ('Action', {
            'fields': ('action_type', 'target_path', 'target_view_name', 'open_in_new_tab')
        }),
        ('Advanced', {
            'fields': ('metadata', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not obj.created_by and hasattr(request.user, 'mediap_profile'):
            obj.created_by = request.user.mediap_profile
        super().save_model(request, obj, form, change)


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
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, 'mediap_profile', None)
        return bool(profile and profile.is_organization_admin)


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