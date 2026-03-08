from django.contrib import admin
from django import forms
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import Service, LicenseType, License, LicenseUsageLog, UserLicenseAssignment, CustomLicense, LicenseAuditLog


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'version', 'allows_personal_free', 'is_active', 'sort_order']
    list_filter = ['is_active', 'allows_personal_free', 'created_at']
    search_fields = ['name', 'slug', 'description']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['sort_order', 'name']


class LicenseTypeAdminForm(forms.ModelForm):
    restrictions_csv = forms.CharField(
        label='Restrictions (comma-separated)',
        required=False,
        help_text='Enter restrictions separated by commas, e.g., No team collaboration, Limited integrations'
    )

    class Meta:
        model = LicenseType
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialize CSV field from instance JSON list
        if self.instance and self.instance.pk and isinstance(self.instance.restrictions, list):
            self.fields['restrictions_csv'].initial = ', '.join(self.instance.restrictions)

    def clean(self):
        cleaned = super().clean()
        csv = cleaned.get('restrictions_csv')
        items = [s.strip() for s in (csv.split(',') if csv else []) if s.strip()]
        # Require at least one restriction on create
        if not self.instance.pk and not items:
            raise forms.ValidationError('Please provide at least one restriction for the license type.')
        cleaned['restrictions_parsed'] = items
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        items = self.cleaned_data.get('restrictions_parsed', [])
        # If editing and CSV was left blank, keep existing restrictions; otherwise set parsed
        if self.instance.pk and not self.cleaned_data.get('restrictions_csv'):
            pass  # keep existing instance.restrictions
        else:
            instance.restrictions = items
        if commit:
            instance.save()
            self.save_m2m()
        return instance


@admin.register(LicenseType)
class LicenseTypeAdmin(admin.ModelAdmin):
    form = LicenseTypeAdminForm
    list_display = ['display_name', 'service', 'name', 'price_monthly', 'price_yearly', 'max_users', 'max_workflows', 'is_active']
    list_filter = ['service', 'name', 'is_active', 'is_personal_only', 'requires_organization']
    search_fields = ['display_name', 'service__name']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        (None, {
            'fields': ('service', 'name', 'display_name', 'is_active')
        }),
        ('Pricing', {
            'fields': ('price_monthly', 'price_yearly')
        }),
        ('Limits', {
            'fields': ('max_users', 'max_projects', 'max_workflows', 'max_storage_gb', 'max_api_calls_per_day')
        }),
        ('Features & Restrictions', {
            'fields': ('features', 'restrictions_csv'),
            'classes': ('collapse',)
        }),
        ('Account Types', {
            'fields': ('is_personal_only', 'requires_organization')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    list_display = ['organization', 'license_type', 'account_type', 'status', 'usage_summary', 'start_date', 'end_date']
    list_filter = ['status', 'account_type', 'is_personal_free', 'license_type__service', 'billing_cycle']
    search_fields = ['organization__name', 'license_type__display_name', 'notes']
    raw_id_fields = ['organization', 'created_by']
    readonly_fields = ['created_at', 'updated_at', 'usage_summary']
    date_hierarchy = 'start_date'
    
    fieldsets = (
        (None, {
            'fields': ('organization', 'license_type', 'status')
        }),
        ('Account Information', {
            'fields': ('account_type', 'is_personal_free')
        }),
        ('License Period', {
            'fields': ('start_date', 'end_date', 'trial_end_date', 'billing_cycle')
        }),
        ('Usage Tracking', {
            'fields': ('usage_summary', 'current_users', 'current_projects', 'current_workflows', 'current_storage_gb')
        }),
        ('API Usage', {
            'fields': ('current_api_calls_today', 'api_calls_reset_date'),
            'classes': ('collapse',)
        }),
        ('Billing', {
            'fields': ('last_billing_date', 'next_billing_date', 'amount_paid'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('notes', 'created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def usage_summary(self, obj):
        """Display usage summary as colored bars"""
        html = []
        for resource in ['users', 'projects', 'workflows', 'storage_gb']:
            percentage = obj.usage_percentage(resource)
            if percentage > 0:
                color = '#dc3545' if percentage >= 90 else '#ffc107' if percentage >= 75 else '#28a745'
                html.append(
                    f'<div style="margin: 2px 0;"><strong>{resource.replace("_", " ").title()}:</strong> '
                    f'<div style="display: inline-block; width: 100px; height: 10px; background: #f8f9fa; border-radius: 5px; margin: 0 5px;">'
                    f'<div style="width: {percentage}%; height: 100%; background: {color}; border-radius: 5px;"></div></div> '
                    f'{percentage:.1f}%</div>'
                )
        return mark_safe(''.join(html)) if html else 'No usage data'
    usage_summary.short_description = 'Usage'


@admin.register(LicenseUsageLog)
class LicenseUsageLogAdmin(admin.ModelAdmin):
    list_display = ['license', 'users_count', 'projects_count', 'storage_gb', 'api_calls', 'recorded_at']
    list_filter = ['recorded_at', 'license__license_type__service']
    search_fields = ['license__organization__name']
    raw_id_fields = ['license']
    readonly_fields = ['recorded_at']
    date_hierarchy = 'recorded_at'
    
    def has_add_permission(self, request):
        return False  # Usage logs are created automatically


@admin.register(CustomLicense)
class CustomLicenseAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'service', 'max_users', 'assigned_users', 'remaining_seats', 'is_valid_status', 'created_by', 'created_at']
    list_filter = ['service', 'is_active', 'created_at', 'end_date']
    search_fields = ['name', 'organization__name', 'service__name', 'description']
    raw_id_fields = ['organization', 'created_by']
    readonly_fields = ['created_at', 'updated_at', 'assigned_users', 'remaining_seats', 'is_valid_status']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        (None, {
            'fields': ('name', 'organization', 'service', 'is_active')
        }),
        ('License Details', {
            'fields': ('max_users', 'description', 'assigned_users', 'remaining_seats')
        }),
        ('Validity Period', {
            'fields': ('start_date', 'end_date', 'is_valid_status')
        }),
        ('Features & Restrictions', {
            'fields': ('included_features', 'restrictions'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at', 'notes'),
            'classes': ('collapse',)
        })
    )
    
    def assigned_users(self, obj):
        """Display number of assigned users with link to assignments"""
        count = UserLicenseAssignment.objects.filter(
            license__custom_license=obj,
            is_active=True
        ).count()
        
        if count > 0:
            url = reverse('admin:licensing_userlicenseassignment_changelist')
            return mark_safe(f'<a href="{url}?license__custom_license={obj.id}&is_active=1">{count} users</a>')
        return "0 users"
    assigned_users.short_description = 'Assigned Users'
    
    def remaining_seats(self, obj):
        """Display remaining seats with color coding"""
        remaining = obj.remaining_seats()
        total = obj.max_users
        percentage = (remaining / total) * 100 if total > 0 else 0
        
        color = '#dc3545' if percentage < 10 else '#ffc107' if percentage < 25 else '#28a745'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} / {}</span>',
            color, remaining, total
        )
    remaining_seats.short_description = 'Available Seats'
    
    def is_valid_status(self, obj):
        """Display validity status with color"""
        is_valid = obj.is_valid()
        color = '#28a745' if is_valid else '#dc3545'
        status = 'Valid' if is_valid else 'Invalid'
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, status)
    is_valid_status.short_description = 'Status'


@admin.register(UserLicenseAssignment)
class UserLicenseAssignmentAdmin(admin.ModelAdmin):
    list_display = ['user_profile', 'service_name', 'organization', 'assigned_at', 'is_active', 'last_access', 'assigned_by']
    list_filter = ['is_active', 'license__license_type__service', 'assigned_at', 'license__organization']
    search_fields = ['user_profile__user__username', 'user_profile__user__email', 'license__organization__name']
    raw_id_fields = ['user_profile', 'assigned_by', 'revoked_by']
    readonly_fields = ['assigned_at', 'total_sessions', 'service_name', 'organization']
    date_hierarchy = 'assigned_at'
    
    fieldsets = (
        (None, {
            'fields': ('user_profile', 'license', 'is_active')
        }),
        ('Assignment Details', {
            'fields': ('assigned_at', 'assigned_by', 'service_name', 'organization')
        }),
        ('Revocation Details', {
            'fields': ('revoked_at', 'revoked_by'),
            'classes': ('collapse',)
        }),
        ('Usage Tracking', {
            'fields': ('last_access', 'total_sessions'),
            'classes': ('collapse',)
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        })
    )
    
    def service_name(self, obj):
        """Get service name from license"""
        if obj.license.custom_license:
            return obj.license.custom_license.service.name
        return obj.license.license_type.service.name
    service_name.short_description = 'Service'
    
    def organization(self, obj):
        """Get organization name"""
        return obj.license.organization.name
    organization.short_description = 'Organization'
    
    actions = ['revoke_assignments']
    
    def revoke_assignments(self, request, queryset):
        """Bulk revoke license assignments"""
        count = 0
        for assignment in queryset.filter(is_active=True):
            assignment.revoke(request.user)
            count += 1
        
        self.message_user(request, f'Successfully revoked {count} license assignments.')
    revoke_assignments.short_description = 'Revoke selected assignments'


@admin.register(LicenseAuditLog)
class LicenseAuditLogAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'action', 'license_info', 'performed_by', 'affected_user', 'description']
    list_filter = ['action', 'timestamp', 'license__license_type__service']
    search_fields = ['description', 'performed_by__username', 'affected_user__user__username']
    raw_id_fields = ['license', 'custom_license', 'user_assignment', 'performed_by', 'affected_user']
    readonly_fields = ['timestamp', 'license_info']
    date_hierarchy = 'timestamp'
    
    fieldsets = (
        (None, {
            'fields': ('action', 'performed_by', 'affected_user', 'timestamp')
        }),
        ('License Information', {
            'fields': ('license', 'custom_license', 'user_assignment', 'license_info')
        }),
        ('Details', {
            'fields': ('description', 'old_values', 'new_values')
        }),
        ('Metadata', {
            'fields': ('ip_address',),
            'classes': ('collapse',)
        })
    )
    
    def license_info(self, obj):
        """Display license information"""
        if obj.license:
            return f"{obj.license.organization.name} - {obj.license.license_type.service.name}"
        elif obj.custom_license:
            return f"{obj.custom_license.organization.name} - {obj.custom_license.service.name} (Custom)"
        return "N/A"
    license_info.short_description = 'License'
    
    def has_add_permission(self, request):
        return False  # Audit logs are created automatically
    
    def has_change_permission(self, request, obj=None):
        return False  # Audit logs should not be modified
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser  # Only superusers can delete audit logs
