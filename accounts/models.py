from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models
from django.utils.text import slugify
from django.utils import timezone
from typing import List, Set, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.permissions import Permission, Role, UserRoleAssignment


class CustomUser(AbstractUser):
    """
    Extended user model for MetaTask platform
    """
    REFERRAL_SOURCES = [
        ('search', 'Search Engine'),
        ('social_media', 'Social Media'),
        ('referral', 'Referral'),
        ('advertisement', 'Advertisement'),
        ('direct', 'Direct Visit'),
        ('other', 'Other'),
    ]
    
    TEAM_SIZES = [
        ('1', 'Just Me'),
        ('2-10', '2-10 people'),
        ('11-50', '11-50 people'),
        ('51-200', '51-200 people'),
        ('201-500', '201-500 people'),
        ('500+', '500+ people'),
    ]
    
    # Extended fields
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150) 
    phone_number = models.CharField(
        max_length=17,
        blank=True,
        validators=[RegexValidator(regex=r'^\+?1?\d{9,15}$', 
                                 message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.")]
    )

    # Additional fields for user management
    display_username = models.CharField(max_length=150, blank=True)

    
    # Registration info
    referral_source = models.CharField(max_length=20, choices=REFERRAL_SOURCES, blank=True)
    team_size = models.CharField(max_length=10, choices=TEAM_SIZES, blank=True)
    job_title = models.CharField(max_length=255, blank=True)
    organization_name = models.CharField(max_length=255, blank=True)
    
    # GDPR compliance fields
    privacy_policy_accepted = models.BooleanField(default=False)
    privacy_policy_accepted_date = models.DateTimeField(null=True, blank=True)
    terms_accepted = models.BooleanField(default=False)
    terms_accepted_date = models.DateTimeField(null=True, blank=True)
    marketing_consent = models.BooleanField(default=False)
    
    # Settings
    timezone = models.CharField(max_length=50, default='UTC')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        raw_username = (self.username or "").strip()
        if raw_username:
            if not self.display_username:
                self.display_username = raw_username
            self.username = raw_username.lower()
        elif self.display_username:
            # Fallback if username is empty but display value exists
            self.username = self.display_username.strip().lower()

        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.username} ({self.email})"
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


# Organization model moved to core.models to avoid duplication
# Use: from core.models import Organization


class UserRole(models.Model):
    """
    User role model for MetaTask platform role management
    """
    ROLE_CHOICES = [
        ('metatask_support', 'MetaTask Support'),
        ('metatask_admin', 'MetaTask Admin'),
        ('metatask_moderator', 'MetaTask Moderator'),
        ('metatask_editor', 'MetaTask Editor'),
        ('workflow_manager', 'Workflow Manager'),
        ('process_designer', 'Process Designer'),
        ('job_planner', 'Job Planner'),
        ('resource_manager', 'Resource Manager'),
        ('team_leader', 'Team Leader'),
        ('standard_user', 'Standard User'),
    ]
    
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='roles')
    role = models.CharField(max_length=50, choices=ROLE_CHOICES)
    service = models.CharField(max_length=100, blank=True, help_text="Service this role applies to (e.g., 'cflows', 'scheduling')")
    granted_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='granted_roles')
    granted_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ['user', 'role', 'service']
        indexes = [
            models.Index(fields=['user', 'role']),
            models.Index(fields=['service']),
        ]
    
    def __str__(self):
        service_str = f" ({self.service})" if self.service else ""
        return f"{self.user.username} - {self.get_role_display()}{service_str}"


class UserProfile(models.Model):
    """
    Extended user profile for additional MetaTask-specific data
    """
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='profile')
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    bio = models.TextField(max_length=500, blank=True)
    website = models.URLField(blank=True)
    
    # Organization access
    is_organization_admin = models.BooleanField(default=False)
    
    # Notification preferences
    email_notifications = models.BooleanField(default=True)
    push_notifications = models.BooleanField(default=True)
    digest_frequency = models.CharField(
        max_length=20,
        choices=[
            ('daily', 'Daily'),
            ('weekly', 'Weekly'),
            ('monthly', 'Monthly'),
            ('never', 'Never'),
        ],
        default='weekly'
    )
    
    # Analytics and activity tracking (GDPR compliant)
    analytics_consent = models.BooleanField(default=False)
    last_activity = models.DateTimeField(auto_now=True)
    login_count = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.username}'s Profile"
    
    @property
    def organization(self):
        """Get the user's organization through UserProfile"""
        try:
            # Get the MetaTask profile which has the organization relationship
            mediap_profile = self.user.mediap_profile
            return mediap_profile.organization
        except AttributeError:
            # No mediap_profile exists
            return None
    
    def get_active_roles(self) -> List['Role']:
        """Get all active roles for this user"""
        from core.permissions import UserRoleAssignment
        
        now = timezone.now()
        assignments = UserRoleAssignment.objects.filter(
            user_profile=self,
            is_active=True,
            role__is_active=True
        ).select_related('role')
        
        return [
            assignment.role for assignment in assignments 
            if assignment.is_currently_valid()
        ]
    
    def get_all_permissions(self) -> Set[str]:
        """Get all permission codenames this user has access to"""
        permissions = set()
        
        # Organization admin gets all permissions
        if self.is_organization_admin:
            from core.permissions import Permission
            permissions.update(
                Permission.objects.values_list('codename', flat=True)
            )
            return permissions
        
        # Get permissions from roles
        roles = self.get_active_roles()
        for role in roles:
            # Direct role permissions
            role_permissions = role.permissions.values_list('codename', flat=True)
            permissions.update(role_permissions)
            
            # Inherited permissions from parent roles
            parent_permissions = role.get_inherited_permissions()
            permissions.update(parent_permissions.values_list('codename', flat=True))
        
        return permissions
    
    def has_permission(self, permission_codename: str, resource=None) -> bool:
        """
        Check if user has a specific permission
        
        Args:
            permission_codename: The permission code to check
            resource: Optional resource object for resource-scoped permissions
        """
        # Organization admin has all permissions
        if self.is_organization_admin:
            return True
        
        # Check if user has permission through roles
        permissions = self.get_all_permissions()
        if permission_codename not in permissions:
            return False
        
        # If no resource specified, user has the permission
        if not resource:
            return True
        
        # Check resource-scoped permissions
        from core.permissions import UserRoleAssignment
        from django.contrib.contenttypes.models import ContentType
        
        resource_type = ContentType.objects.get_for_model(resource.__class__)
        
        # Check if user has role assignment for this specific resource
        has_resource_access = UserRoleAssignment.objects.filter(
            user_profile=self,
            is_active=True,
            role__is_active=True,
            role__permissions__codename=permission_codename,
            resource_type=resource_type,
            resource_id=resource.id
        ).exists()
        
        if has_resource_access:
            return True
        
        # Check if user has global permission (not resource-scoped)
        has_global_access = UserRoleAssignment.objects.filter(
            user_profile=self,
            is_active=True,
            role__is_active=True,
            role__permissions__codename=permission_codename,
            resource_type__isnull=True
        ).exists()
        
        return has_global_access
    
    def can_manage_roles(self) -> bool:
        """Check if user can manage roles in their organization"""
        return self.is_organization_admin or self.has_permission('user.manage_roles')
    
    def can_create_workflows(self) -> bool:
        """Check if user can create workflows"""
        return self.has_permission('workflow.create')
    
    def can_manage_team(self, team=None) -> bool:
        """Check if user can manage team members"""
        if team:
            return self.has_permission('team.manage_members', team)
        return self.has_permission('team.manage_members')
    
    def get_accessible_resources(self, permission_codename: str, resource_class):
        """Get all resources of a given type that user has permission to access"""
        from core.permissions import UserRoleAssignment
        from django.contrib.contenttypes.models import ContentType
        
        if self.is_organization_admin:
            # Admin can access all resources
            return resource_class.objects.all()
        
        resource_type = ContentType.objects.get_for_model(resource_class)
        
        # Get resource IDs from role assignments
        resource_assignments = UserRoleAssignment.objects.filter(
            user_profile=self,
            is_active=True,
            role__is_active=True,
            role__permissions__codename=permission_codename,
            resource_type=resource_type
        ).values_list('resource_id', flat=True)
        
        # Get global assignments (no resource restriction)
        has_global = UserRoleAssignment.objects.filter(
            user_profile=self,
            is_active=True,
            role__is_active=True,
            role__permissions__codename=permission_codename,
            resource_type__isnull=True
        ).exists()
        
        if has_global:
            return resource_class.objects.all()
        elif resource_assignments:
            return resource_class.objects.filter(id__in=resource_assignments)
        else:
            return resource_class.objects.none()
