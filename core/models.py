from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.text import slugify
from django.utils import timezone
import uuid


class BaseModel(models.Model):
    """
    Base model with common fields for all MetaTask models
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_created'
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_updated'
    )
    
    class Meta:
        abstract = True


class AuditLog(models.Model):
    """
    Audit log for tracking user actions across the platform
    """
    ACTION_TYPES = [
        ('create', 'Create'),
        ('read', 'Read'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('permission_granted', 'Permission Granted'),
        ('permission_revoked', 'Permission Revoked'),
        ('export', 'Data Export'),
        ('import', 'Data Import'),
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=20, choices=ACTION_TYPES)
    content_type = models.CharField(max_length=100, help_text="Model name")
    object_id = models.CharField(max_length=100, blank=True)
    object_repr = models.CharField(max_length=200, blank=True)
    
    # Request information
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    # Additional context
    changes = models.JSONField(default=dict, help_text="Changed fields and values")
    additional_data = models.JSONField(default=dict, help_text="Additional context data")
    
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['timestamp']),
        ]
        ordering = ['-timestamp']
    
    def __str__(self):
        user_str = self.user.username if self.user else 'Anonymous'
        return f"{user_str} {self.action} {self.content_type} at {self.timestamp}"


class SystemConfiguration(models.Model):
    """
    System-wide configuration settings
    """
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    value_type = models.CharField(
        max_length=20,
        choices=[
            ('string', 'String'),
            ('integer', 'Integer'),
            ('boolean', 'Boolean'),
            ('json', 'JSON'),
            ('float', 'Float'),
        ],
        default='string'
    )
    description = models.TextField(blank=True)
    category = models.CharField(max_length=50, default='general')
    is_sensitive = models.BooleanField(default=False, help_text="Whether this setting contains sensitive data")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    
    class Meta:
        ordering = ['category', 'key']
        indexes = [
            models.Index(fields=['category']),
        ]
    
    def __str__(self):
        return f"{self.key} = {self.value[:50]}..."
    
    def get_typed_value(self):
        """Return the value converted to its proper type"""
        if self.value_type == 'integer':
            return int(self.value)
        elif self.value_type == 'boolean':
            return self.value.lower() in ('true', '1', 'yes')
        elif self.value_type == 'float':
            return float(self.value)
        elif self.value_type == 'json':
            import json
            return json.loads(self.value)
        else:
            return self.value


class Notification(models.Model):
    """
    In-app notification system
    """
    NOTIFICATION_TYPES = [
        ('info', 'Information'),
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('system', 'System'),
    ]
    
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='info')
    
    # Link to related object
    content_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=100, blank=True)
    action_url = models.URLField(blank=True, help_text="URL for action button")
    action_text = models.CharField(max_length=50, blank=True)
    
    # Status tracking
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    
    # Email/push notification status
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Auto-delete after this date")
    
    class Meta:
        indexes = [
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['created_at']),
            models.Index(fields=['expires_at']),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} for {self.recipient.username}"
    
    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            from django.utils import timezone
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])


class FileUpload(models.Model):
    """
    Generic file upload model for the platform
    """
    file = models.FileField(upload_to='uploads/%Y/%m/')
    original_filename = models.CharField(max_length=255)
    file_size = models.BigIntegerField()
    mime_type = models.CharField(max_length=100)
    
    # File metadata
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    upload_session = models.UUIDField(default=uuid.uuid4, help_text="Group related files")
    
    # Content association
    content_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=100, blank=True)
    
    # File processing status
    is_processed = models.BooleanField(default=False)
    processing_error = models.TextField(blank=True)
    
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['uploaded_by', 'uploaded_at']),
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['upload_session']),
        ]
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return f"{self.original_filename} by {self.uploaded_by.username}"
    
    @property
    def file_size_human(self):
        """Return human readable file size"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if self.file_size < 1024.0:
                return f"{self.file_size:.1f} {unit}"
            self.file_size /= 1024.0
        return f"{self.file_size:.1f} TB"


class Organization(models.Model):
    """Multi-tenant organization model for complete data isolation across all services"""
    ORGANIZATION_TYPES = [
        ('personal', 'Personal Account'),
        ('business', 'Business'),
        ('enterprise', 'Enterprise'),
        ('non_profit', 'Non-Profit'),
        ('educational', 'Educational'),
        ('government', 'Government'),
    ]
    
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    organization_type = models.CharField(max_length=20, choices=ORGANIZATION_TYPES, default='business')
    
    # Organization settings
    time_format_24h = models.BooleanField(default=True, help_text="Use 24-hour time format")
    timezone = models.CharField(max_length=50, default='UTC')
    
    # Contact information
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    website = models.URLField(blank=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active']),
            models.Index(fields=['organization_type']),
        ]
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        """Generate slug automatically if not provided"""
        if not self.slug:
            base_slug = slugify(self.name)
            if not base_slug:  # If slugify returns empty (e.g., only special characters)
                base_slug = 'organization'
            
            # Ensure slug is unique
            slug = base_slug
            counter = 1
            while Organization.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        
        super().save(*args, **kwargs)
    
    @property
    def is_personal(self):
        """Check if this is a personal account"""
        return self.organization_type == 'personal'
    
    def can_have_multiple_users(self):
        """Check if organization can have multiple users"""
        return not self.is_personal


class UserProfile(models.Model):
    """Extended user information with organization association for all MetaTask services"""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mediap_profile')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='members')
    
    TIMEZONE_CHOICES = [
        ('UTC', 'UTC'),
        ('America/New_York', 'Eastern Time'),
        ('America/Chicago', 'Central Time'),
        ('America/Denver', 'Mountain Time'),
        ('America/Los_Angeles', 'Pacific Time'),
        ('Europe/London', 'London'),
        ('Europe/Paris', 'Paris'),
        ('Asia/Tokyo', 'Tokyo'),
        ('Australia/Sydney', 'Sydney'),
    ]

    # Profile information
    title = models.CharField(max_length=100, blank=True)
    department = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=200, blank=True)
    timezone = models.CharField(max_length=50, default='UTC', choices=TIMEZONE_CHOICES)
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    
    # Contact preferences
    phone = models.CharField(max_length=20, blank=True)
    mobile = models.CharField(max_length=20, blank=True)
    
    # Organization roles
    is_organization_admin = models.BooleanField(default=False)
    has_staff_panel_access = models.BooleanField(default=False)
    can_create_organizations = models.BooleanField(default=False, help_text="Allow user to create new organizations")
    
    # Notification preferences
    email_notifications = models.BooleanField(default=True)
    desktop_notifications = models.BooleanField(default=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'organization']
        ordering = ['user__last_name', 'user__first_name']
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['user']),
        ]
    
    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.organization.name})"
    
    @classmethod
    def can_user_create_organization(cls, user):
        """Check if user can create a new organization"""
        if user.is_superuser:
            return True
        
        # Check if user already has a profile (is part of an organization)
        existing_profile = cls.objects.filter(user=user, is_active=True).first()
        if existing_profile:
            # User is already part of an organization, can't create new one
            return False
        
        # New user without organization can create one
        return True
    
    @classmethod
    def get_user_organizations(cls, user):
        """Get all organizations a user belongs to"""
        return Organization.objects.filter(
            members__user=user, 
            members__is_active=True, 
            is_active=True
        ).distinct()
    
    def can_manage_user_in_location(self, target_user_profile, location=None):
        """Check if user can manage another user in a specific location"""
        # Can't manage users in different organizations
        if self.organization != target_user_profile.organization:
            return False
        
        # Organization admins can manage anyone
        if self.is_organization_admin:
            return True
        
        # Import here to avoid circular imports
        from core.permissions import UserRoleAssignment
        
        # Check if user has HR manager role for the specific location
        hr_assignments = UserRoleAssignment.objects.filter(
            user_profile=self,
            is_active=True,
            role__name__icontains='HR Manager'
        )
        
        for assignment in hr_assignments:
            # Check if assignment has location context that matches
            conditions = assignment.conditions or {}
            if 'location' in conditions and conditions['location'] == location:
                return True
            # If target user's location matches
            if target_user_profile.location == location:
                return True
        
        return False
    
    def can_create_user_in_location(self, location):
        """Check if user can create users in a specific location"""
        if self.is_organization_admin:
            return True
        
        # Import here to avoid circular imports  
        from core.permissions import UserRoleAssignment
        
        # Check if user has HR manager role for the specific location
        hr_assignments = UserRoleAssignment.objects.filter(
            user_profile=self,
            is_active=True,
            role__name__icontains='HR'
        )
        
        for assignment in hr_assignments:
            conditions = assignment.conditions or {}
            if 'location' in conditions and conditions['location'] == location:
                return True
        
        return False
    
    def get_manageable_locations(self):
        """Get list of locations this user can manage users in"""
        if self.is_organization_admin:
            # Return all locations in the organization
            return list(self.organization.members.exclude(location='').values_list('location', flat=True).distinct())
        
        # Import here to avoid circular imports
        from core.permissions import UserRoleAssignment
        
        locations = []
        hr_assignments = UserRoleAssignment.objects.filter(
            user_profile=self,
            is_active=True,
            role__name__icontains='HR'
        )
        
        for assignment in hr_assignments:
            conditions = assignment.conditions or {}
            if 'location' in conditions:
                locations.append(conditions['location'])
        
        return list(set(locations))
    
    def has_role_permission(self, permission_codename, resource=None):
        """Check if user has a specific permission through their roles"""
        if self.is_organization_admin:
            return True
        
        # Import here to avoid circular imports
        from core.permissions import UserRoleAssignment, RolePermission
        
        # Get all active role assignments for this user
        role_assignments = UserRoleAssignment.objects.filter(
            user_profile=self,
            is_active=True
        ).select_related('role')
        
        for assignment in role_assignments:
            # Check if role has the permission
            role_permissions = RolePermission.objects.filter(
                role=assignment.role,
                permission__codename=permission_codename
            )
            
            for role_perm in role_permissions:
                # If no resource context needed, grant permission
                if not resource:
                    return True
                
                # Check resource context if specified
                if role_perm.resource_object == resource:
                    return True
                
                # Check if permission applies globally for this resource type
                if not role_perm.resource_object and type(resource) == role_perm.resource_type.model_class():
                    return True
        
        return False




class Team(models.Model):
    """Teams within organizations - reusable across all services"""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='teams')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    # Sub-team hierarchy
    parent_team = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='sub_teams',
        help_text="Parent team - leave empty for top-level teams"
    )
    
    # Team settings
    color = models.CharField(max_length=7, default='#007bff', help_text='Hex color code for visual identification')
    
    # Capacity management (useful for scheduling/booking systems)
    default_capacity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Default number of team members available for scheduling"
    )
    
    # Team structure
    manager = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_teams')
    members = models.ManyToManyField(UserProfile, related_name='teams', blank=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_teams')
    
    class Meta:
        # Allow same team names under different parent teams
        unique_together = [['organization', 'name', 'parent_team']]
        ordering = ['name']
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['parent_team']),
        ]
    
    def __str__(self):
        if self.parent_team:
            return f"{self.parent_team.name} > {self.name}"
        return f"{self.name}"
    
    @property
    def unique_display_name(self):
        """Get a unique display name including organization context"""
        if self.parent_team:
            return f"{self.parent_team.name} > {self.name} ({self.organization.name})"
        return f"{self.name} ({self.organization.name})"
    
    @property
    def member_count(self):
        return self.members.count()
    
    @property
    def full_hierarchy_name(self):
        """Get the full hierarchical name of the team"""
        if self.parent_team:
            return f"{self.parent_team.full_hierarchy_name} > {self.name}"
        return self.name
    
    @property
    def is_parent_team(self):
        """Check if this team has sub-teams"""
        return self.sub_teams.exists()
    
    @property
    def all_members_count(self):
        """Get count of all members including those in sub-teams"""
        total = self.member_count
        for sub_team in self.sub_teams.all():
            total += sub_team.all_members_count
        return total
    
    def get_all_sub_teams(self, include_self=True):
        """Get all sub-teams recursively"""
        teams = [self] if include_self else []
        for sub_team in self.sub_teams.all():
            teams.extend(sub_team.get_all_sub_teams(include_self=True))
        return teams
    
    def get_team_path(self):
        """Get the hierarchical path to this team"""
        path = []
        current = self
        while current:
            path.insert(0, current)
            current = current.parent_team
        return path
    
    def has_active_bookings(self):
        """Check if this team has any bookings (active or completed)"""
        try:
            from services.cflows.models import TeamBooking
            return TeamBooking.objects.filter(team=self).exists()
        except ImportError:
            # CFlows service might not be available
            return False
    
    def can_remove_member(self, member):
        """Check if a member can be safely removed from the team"""
        if not self.has_active_bookings():
            return True, "No bookings associated with this team"
        
        # Check if removing this member would leave the team empty
        remaining_members = self.members.exclude(id=member.id).filter(is_active=True)
        if not remaining_members.exists():
            return False, "Cannot remove last active member from team with bookings"
        
        return True, "Member can be safely removed"
    
    def delete(self, *args, **kwargs):
        """Override delete to prevent deletion of teams with bookings"""
        if self.has_active_bookings():
            raise ValueError(f"Cannot delete team '{self.name}' because it has associated bookings")
        return super().delete(*args, **kwargs)


class JobType(models.Model):
    """Generic job/work type definitions - reusable across scheduling and workflow systems"""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='job_types')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    # Scheduling defaults
    default_duration_hours = models.DecimalField(max_digits=5, decimal_places=2, default=1.0)
    
    # Visual settings
    color = models.CharField(max_length=7, default='#007bff', help_text="Hex color code for calendar/UI display")
    
    # Categorization
    category = models.CharField(max_length=50, blank=True, help_text="Category for grouping job types")
    
    # Requirements
    required_skills = models.JSONField(default=list, blank=True, help_text="List of required skills/qualifications")
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_job_types')
    
    class Meta:
        unique_together = ['organization', 'name']
        ordering = ['category', 'name']
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['category']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.organization.name})"


class CalendarEvent(models.Model):
    """Generic calendar events - reusable across all services"""
    EVENT_TYPES = [
        ('personal', 'Personal'),
        ('team', 'Team'),
        ('organization', 'Organization'),
        ('system', 'System'),
    ]
    
    # Event identification
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    # Context
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='calendar_events')
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES, default='personal')
    
    # Event details
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=200, blank=True)
    
    # Scheduling
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_all_day = models.BooleanField(default=False)
    timezone = models.CharField(max_length=50, default='UTC')
    
    # Participants
    created_by = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='created_events')
    invitees = models.ManyToManyField(UserProfile, related_name='invited_events', blank=True)
    
    # Optional associations (generic)
    related_team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='team_events')
    
    # Generic foreign key for linking to any model
    content_type = models.CharField(max_length=100, blank=True, help_text="Model type this event relates to")
    object_id = models.CharField(max_length=100, blank=True, help_text="ID of the related object")
    
    # Display settings
    color = models.CharField(max_length=7, default='#007bff', help_text="Hex color code for calendar display")
    
    # Recurrence (for future expansion)
    is_recurring = models.BooleanField(default=False)
    recurrence_pattern = models.JSONField(default=dict, blank=True, help_text="Recurrence pattern configuration")
    
    # Status
    is_cancelled = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['start_time']
        indexes = [
            models.Index(fields=['organization', 'start_time']),
            models.Index(fields=['event_type', 'start_time']),
            models.Index(fields=['created_by', 'start_time']),
            models.Index(fields=['content_type', 'object_id']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.start_time.strftime('%Y-%m-%d %H:%M')})"
