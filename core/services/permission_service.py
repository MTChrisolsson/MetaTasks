"""
Permission management service for RBAC system
"""

from typing import List, Dict, Any, Optional
from django.db import transaction
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from accounts.models import UserProfile
from core.models import Organization
from core.permissions import Permission, Role, UserRoleAssignment


class PermissionService:
    """Service for managing permissions and roles"""
    
    def __init__(self, organization: Organization):
        self.organization = organization
    
    def create_default_permissions(self):
        """Create default permissions for the system"""
        default_permissions = [
            # Workflow permissions
            ('workflow.create', 'Create Workflows', 'Create new workflow definitions', 'workflow', False, 'cflows'),
            ('workflow.edit', 'Edit Workflows', 'Modify existing workflow definitions', 'workflow', False, 'cflows'),
            ('workflow.delete', 'Delete Workflows', 'Remove workflow definitions', 'workflow', False, 'cflows'),
            ('workflow.view', 'View Workflows', 'View workflow definitions and details', 'workflow', False, 'cflows'),
            ('workflow.configure', 'Configure Workflows', 'Configure workflow settings and field customization', 'workflow', False, 'cflows'),
            
            # Work Item permissions
            ('workitem.create', 'Create Work Items', 'Create new work items in workflows', 'workitem', False, 'cflows'),
            ('workitem.edit', 'Edit Work Items', 'Modify work item details and content', 'workitem', False, 'cflows'),
            ('workitem.assign', 'Assign Work Items', 'Assign work items to users', 'workitem', False, 'cflows'),
            ('workitem.transition', 'Transition Work Items', 'Move work items through workflow steps', 'workitem', False, 'cflows'),
            ('workitem.delete', 'Delete Work Items', 'Remove work items from system', 'workitem', False, 'cflows'),
            ('workitem.view', 'View Work Items', 'View work item details and history', 'workitem', False, 'cflows'),
            
            # Team permissions
            ('team.create', 'Create Teams', 'Create new teams within organization', 'team', False, 'core'),
            ('team.edit', 'Edit Teams', 'Modify team settings and membership', 'team', False, 'core'),
            ('team.delete', 'Delete Teams', 'Remove teams from organization', 'team', False, 'core'),
            ('team.manage_members', 'Manage Team Members', 'Add/remove team members', 'team', False, 'core'),
            ('team.view', 'View Teams', 'View team information and membership', 'team', False, 'core'),
            
            # User management permissions
            ('user.invite', 'Invite Users', 'Invite new users to organization', 'user', False, 'core'),
            ('user.manage_roles', 'Manage User Roles', 'Assign and remove user roles', 'user', False, 'core'),
            ('user.deactivate', 'Deactivate Users', 'Deactivate user accounts', 'user', False, 'core'),
            ('user.view', 'View Users', 'View user profiles and information', 'user', False, 'core'),
            ('user.edit', 'Edit Users', 'Modify user profiles and settings', 'user', False, 'core'),
            
            # Booking permissions
            ('booking.create', 'Create Bookings', 'Create team bookings and reservations', 'booking', False, 'cflows'),
            ('booking.edit', 'Edit Bookings', 'Modify existing bookings', 'booking', False, 'cflows'),
            ('booking.complete', 'Complete Bookings', 'Mark bookings as completed', 'booking', False, 'cflows'),
            ('booking.view', 'View Bookings', 'View booking information and schedules', 'booking', False, 'cflows'),
            ('booking.delete', 'Delete Bookings', 'Remove bookings from system', 'booking', False, 'cflows'),
            
            # Scheduling permissions
            ('scheduling.create', 'Create Schedules', 'Create scheduling entries and resources', 'booking', False, 'scheduling'),
            ('scheduling.edit', 'Edit Schedules', 'Modify scheduling entries', 'booking', False, 'scheduling'),
            ('scheduling.view', 'View Schedules', 'View scheduling information and calendar', 'booking', False, 'scheduling'),

            # Inventory permissions
            ('inventory.view', 'View Inventory', 'View inventory items, stock levels, and movement history', 'custom', False, 'inventory'),
            ('inventory.create', 'Create Inventory Records', 'Create inventory items and locations', 'custom', False, 'inventory'),
            ('inventory.adjust', 'Adjust Inventory', 'Receive stock, issue stock, and make stock adjustments', 'custom', False, 'inventory'),
            ('inventory.transfer', 'Transfer Inventory', 'Transfer stock between locations', 'custom', False, 'inventory'),
            ('inventory.import', 'Import Inventory Data', 'Import inventory data from external files', 'custom', False, 'inventory'),
            ('inventory.export', 'Export Inventory Data', 'Export inventory balances and movement history', 'custom', False, 'inventory'),
            ('inventory.manage_config', 'Manage Inventory Configuration', 'Manage inventory fields, movement reasons, and service settings', 'custom', False, 'inventory'),
            
            # Reporting permissions
            ('reports.view', 'View Reports', 'Access reporting and analytics features', 'reporting', False, 'core'),
            ('reports.export', 'Export Reports', 'Export report data', 'reporting', False, 'core'),
            
            # System permissions
            ('organization.admin', 'Organization Admin', 'Full administrative access to organization', 'system', True, 'core'),
            ('organization.settings', 'Organization Settings', 'Modify organization settings and configuration', 'system', False, 'core'),
            ('customfields.manage', 'Manage Custom Fields', 'Create and modify custom fields', 'system', False, 'cflows'),
        ]
        
        permissions = []
        for perm_data in default_permissions:
            permission, created = Permission.objects.get_or_create(
                codename=perm_data[0],
                defaults={
                    'name': perm_data[1],
                    'description': perm_data[2],
                    'category': perm_data[3],
                    'is_global': perm_data[4],
                    'service': perm_data[5],
                }
            )
            permissions.append(permission)
        
        return permissions
    
    def create_default_roles(self):
        """Create default roles for organization"""
        permissions = self.create_default_permissions()
        
        # Organization Administrator
        admin_role, created = Role.objects.get_or_create(
            organization=self.organization,
            name='Organization Administrator',
            defaults={
                'description': 'Full administrative access to all organization features',
                'role_type': 'system',
                'color': '#DC2626',
                'is_default': False
            }
        )
        
        if created:
            # Give all permissions to admin role
            admin_role.permissions.set(permissions)
        
        # Workflow Manager
        workflow_manager, created = Role.objects.get_or_create(
            organization=self.organization,
            name='Workflow Manager',
            defaults={
                'description': 'Can create and manage workflows and work items',
                'role_type': 'system',
                'color': '#7C3AED',
                'is_default': False
            }
        )
        
        if created:
            workflow_perms = Permission.objects.filter(
                codename__in=[
                    'workflow.create', 'workflow.edit', 'workflow.view', 'workflow.configure',
                    'workitem.create', 'workitem.edit', 'workitem.assign', 
                    'workitem.transition', 'workitem.view',
                    'team.view', 'user.view', 'booking.create', 'booking.edit', 
                    'booking.complete', 'booking.view', 'customfields.manage',
                    'inventory.view', 'inventory.create', 'inventory.adjust',
                    'inventory.transfer', 'inventory.import', 'inventory.export',
                    'inventory.manage_config'
                ]
            )
            workflow_manager.permissions.set(workflow_perms)
        
        # Team Lead
        team_lead, created = Role.objects.get_or_create(
            organization=self.organization,
            name='Team Lead',
            defaults={
                'description': 'Can manage team members and work items assigned to their team',
                'role_type': 'system',
                'color': '#059669',
                'is_default': False
            }
        )
        
        if created:
            team_perms = Permission.objects.filter(
                codename__in=[
                    'workitem.edit', 'workitem.assign', 'workitem.transition', 'workitem.view',
                    'team.manage_members', 'team.view',
                    'booking.create', 'booking.edit', 'booking.complete', 'booking.view',
                    'user.view', 'workflow.view',
                    'inventory.view', 'inventory.adjust', 'inventory.transfer'
                ]
            )
            team_lead.permissions.set(team_perms)
        
        # Team Member (default)
        team_member, created = Role.objects.get_or_create(
            organization=self.organization,
            name='Team Member',
            defaults={
                'description': 'Basic access to work items and team information',
                'role_type': 'system',
                'color': '#6B7280',
                'is_default': True
            }
        )
        
        if created:
            member_perms = Permission.objects.filter(
                codename__in=[
                    'workitem.view', 'workitem.edit', 'workitem.transition',
                    'team.view', 'booking.view', 'user.view', 'workflow.view',
                    'scheduling.view', 'inventory.view'
                ]
            )
            team_member.permissions.set(member_perms)
        
        return [admin_role, workflow_manager, team_lead, team_member]
    
    @transaction.atomic
    def assign_role_to_user(
        self, 
        user_profile: UserProfile, 
        role: Role,
        assigned_by: UserProfile,
        resource=None,
        valid_from=None,
        valid_until=None,
        notes="",
        skip_permission_check=False
    ) -> UserRoleAssignment:
        """Assign a role to a user with optional constraints"""
        
        # Check if assigner has permission (skip for administrative setup)
        if not skip_permission_check and hasattr(assigned_by, 'can_manage_roles'):
            if not assigned_by.can_manage_roles():
                raise PermissionError("User does not have permission to assign roles")
        
        # Check role capacity
        if role.max_users and role.get_user_count() >= role.max_users:
            raise ValueError(f"Role {role.name} has reached maximum user capacity")
        
        # Create or update assignment
        assignment, created = UserRoleAssignment.objects.get_or_create(
            user_profile=user_profile,
            role=role,
            resource_type=ContentType.objects.get_for_model(resource.__class__) if resource else None,
            resource_id=resource.id if resource else None,
            defaults={
                'assigned_by': assigned_by,
                'valid_from': valid_from,
                'valid_until': valid_until,
                'notes': notes,
                'is_active': True
            }
        )
        
        if not created:
            # Update existing assignment
            assignment.valid_from = valid_from
            assignment.valid_until = valid_until
            assignment.notes = notes
            assignment.is_active = True
            assignment.assigned_by = assigned_by
            assignment.save()
        
        return assignment
    
    def get_user_roles(self, user_profile: UserProfile) -> List[Role]:
        """Get all active roles for a user"""
        assignments = UserRoleAssignment.objects.filter(
            user_profile=user_profile,
            is_active=True,
            role__organization=self.organization,
            role__is_active=True
        ).select_related('role')
        
        return [assignment.role for assignment in assignments if assignment.is_currently_valid()]
    
    def can_user_access_resource(self, user_profile: UserProfile, permission_codename: str, resource=None) -> bool:
        """Check if user can access specific resource with given permission"""
        return user_profile.has_permission(permission_codename, resource)
    
    def get_available_permissions(self) -> Dict[str, List[Permission]]:
        """Get all available permissions grouped by category"""
        permissions = Permission.objects.all().order_by('category', 'name')
        grouped_permissions = {}
        
        for permission in permissions:
            category = permission.get_category_display()
            if category not in grouped_permissions:
                grouped_permissions[category] = []
            grouped_permissions[category].append(permission)
        
        return grouped_permissions
    
    def assign_default_role(self, user_profile: UserProfile):
        """Assign default role to new user"""
        default_role = Role.objects.filter(
            organization=self.organization,
            is_default=True,
            is_active=True
        ).first()
        
        if default_role:
            self.assign_role_to_user(
                user_profile=user_profile,
                role=default_role,
                assigned_by=user_profile,  # Self-assigned for new users
                notes="Default role assignment for new user"
            )
    
    def has_permission(self, user_profile: UserProfile, permission_codename: str, resource=None) -> bool:
        """
        Check if user has a specific permission
        
        Args:
            user_profile: UserProfile instance
            permission_codename: String like 'workflow.create'
            resource: Optional resource for context-specific checks
        
        Returns:
            bool: True if user has permission
        """
        # Organization admins have all permissions
        if user_profile.is_organization_admin:
            return True
        
        # Staff panel access gives many permissions
        if user_profile.has_staff_panel_access and permission_codename in [
            'workflow.create', 'workflow.edit', 'workflow.configure',
            'team.create', 'team.edit', 'user.view', 'reports.view'
        ]:
            return True
        
        # Check role-based permissions
        user_roles = self.get_user_roles(user_profile)
        for role in user_roles:
            if role.permissions.filter(codename=permission_codename).exists():
                return True
        
        return False

    def get_missing_permission_message(self, permission_codename: str) -> str:
        """Get user-friendly message for missing permission"""
        permission_messages = {
            'workflow.create': 'You need permission to create workflows. Contact your administrator to get the "Workflow Manager" role.',
            'workflow.edit': 'You need permission to edit workflows. Contact your administrator for access.',
            'workflow.configure': 'You need permission to configure workflow settings. Contact your administrator for access.',
            'team.create': 'You need permission to create teams. Contact your administrator for the "Team Lead" role.',
            'team.edit': 'You need permission to edit teams. Contact your administrator for access.',
            'user.invite': 'You need permission to invite users. Contact your administrator for the "HR Manager" role.',
            'user.manage_roles': 'You need permission to manage user roles. Contact your administrator for access.',
            'workitem.create': 'You need permission to create work items. Contact your administrator for access.',
            'workitem.edit': 'You need permission to edit work items. Contact your administrator for access.',
            'booking.create': 'You need permission to create bookings. Contact your administrator for access.',
            'inventory.view': 'You need permission to view inventory. Contact your administrator for access.',
            'inventory.create': 'You need permission to create inventory records. Contact your administrator for access.',
            'inventory.adjust': 'You need permission to adjust inventory stock. Contact your administrator for access.',
            'inventory.transfer': 'You need permission to transfer inventory between locations. Contact your administrator for access.',
            'inventory.import': 'You need permission to import inventory data. Contact your administrator for access.',
            'inventory.export': 'You need permission to export inventory data. Contact your administrator for access.',
            'inventory.manage_config': 'You need permission to manage inventory configuration. Contact your administrator for access.',
            'reports.view': 'You need permission to view reports. Contact your administrator for access.',
        }
        
        return permission_messages.get(
            permission_codename, 
            f'You need the "{permission_codename}" permission. Contact your administrator for access.'
        )
