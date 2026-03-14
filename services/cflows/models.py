from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from core.models import Organization, UserProfile, Team, JobType, CalendarEvent
import json
import uuid


class WorkflowTemplate(models.Model):
    """Reusable workflow templates"""
    name = models.CharField(max_length=200)
    description = models.TextField()
    category = models.CharField(max_length=100, default='General')
    
    # Template configuration
    is_public = models.BooleanField(default=False, help_text="Available to all organizations")
    created_by_org = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True, blank=True, related_name='workflow_templates')
    
    # Template data (JSON structure for steps and transitions)
    template_data = models.JSONField(default=dict, help_text="Template configuration for steps and transitions")
    
    # Metadata
    usage_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['category', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.category})"


class Workflow(models.Model):
    """Organization-scoped workflow definitions"""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='workflows')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Workflow hierarchy
    parent_workflow = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='sub_workflows',
        help_text="Parent workflow - leave empty for top-level workflows"
    )
    
    # Template relationship
    template = models.ForeignKey(WorkflowTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='workflows')
    
    # Team-based access control
    owner_team = models.ForeignKey(
        'core.Team',
        on_delete=models.CASCADE,
        related_name='owned_workflows',
        help_text="The team that owns and manages this workflow"
    )
    allowed_view_teams = models.ManyToManyField(
        Team,
        blank=True,
        related_name='viewable_workflows',
        help_text="Teams that can view this workflow and its work items"
    )
    allowed_edit_teams = models.ManyToManyField(
        Team,
        blank=True,
        related_name='editable_workflows', 
        help_text="Teams that can edit this workflow and create work items"
    )
    
    # Workflow metadata
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    
    # Permissions and sharing
    is_shared = models.BooleanField(default=False, help_text="Share with other organizations")
    allowed_organizations = models.ManyToManyField(Organization, blank=True, related_name='shared_workflows')
    
    # Advanced settings
    auto_assign = models.BooleanField(default=False, help_text="Auto-assign work items to team members")
    requires_approval = models.BooleanField(default=False, help_text="Workflow changes require approval")
    
    # Field customization settings
    field_config = models.JSONField(default=dict, blank=True, help_text="Configuration for which standard fields to show/hide/replace")
    
    created_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, related_name='created_workflows')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        # Allow same workflow names under different parent workflows
        unique_together = [['organization', 'name', 'parent_workflow']]
        ordering = ['name']
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['parent_workflow']),
        ]
    
    def __str__(self):
        if self.parent_workflow:
            return f"{self.parent_workflow.name} > {self.name}"
        return f"{self.name}"
    
    @property
    def unique_display_name(self):
        """Get a unique display name including organization context"""
        if self.parent_workflow:
            return f"{self.parent_workflow.name} > {self.name} ({self.organization.name})"
        return f"{self.name} ({self.organization.name})"
    
    @property
    def full_hierarchy_name(self):
        """Get the full hierarchical name of the workflow"""
        if self.parent_workflow:
            return f"{self.parent_workflow.full_hierarchy_name} > {self.name}"
        return self.name
    
    @property
    def is_parent_workflow(self):
        """Check if this workflow has sub-workflows"""
        return self.sub_workflows.exists()
    
    def get_all_sub_workflows(self, include_self=True):
        """Get all sub-workflows recursively"""
        workflows = [self] if include_self else []
        for sub_workflow in self.sub_workflows.all():
            workflows.extend(sub_workflow.get_all_sub_workflows(include_self=True))
        return workflows
    
    def get_workflow_path(self):
        """Get the hierarchical path to this workflow"""
        path = []
        current = self
        while current:
            path.insert(0, current)
            current = current.parent_workflow
        return path
    
    def can_user_view(self, user_profile):
        """Check if a user can view this workflow"""
        # Owner team members can always view
        if user_profile in self.owner_team.members.all():
            return True
        
        # Check if user is in any allowed view teams (includes sub-teams)
        user_teams = user_profile.teams.all()
        for team in user_teams:
            # Check direct team access
            if team in self.allowed_view_teams.all():
                return True
            # Check if any parent team has access
            current_team = team
            while current_team.parent_team:
                current_team = current_team.parent_team
                if current_team in self.allowed_view_teams.all():
                    return True
        
        # Check if user is in any allowed edit teams (edit implies view)
        for team in user_teams:
            if team in self.allowed_edit_teams.all():
                return True
            # Check parent teams for edit access
            current_team = team
            while current_team.parent_team:
                current_team = current_team.parent_team
                if current_team in self.allowed_edit_teams.all():
                    return True
        
        # Organization admins can always view
        if user_profile.is_organization_admin:
            return True
            
        return False
    
    def can_user_edit(self, user_profile):
        """Check if a user can edit this workflow"""
        # Owner team members can always edit
        if user_profile in self.owner_team.members.all():
            return True
        
        # Check if user is in any allowed edit teams (includes sub-teams)
        user_teams = user_profile.teams.all()
        for team in user_teams:
            # Check direct team access
            if team in self.allowed_edit_teams.all():
                return True
            # Check if any parent team has access
            current_team = team
            while current_team.parent_team:
                current_team = current_team.parent_team
                if current_team in self.allowed_edit_teams.all():
                    return True
        
        # Organization admins can always edit
        if user_profile.is_organization_admin:
            return True
            
        return False
    
    def can_user_manage(self, user_profile):
        """Check if a user can manage this workflow (change permissions, delete, etc.)"""
        # Only owner team members and org admins can manage
        if user_profile in self.owner_team.members.all():
            return True
        
        if user_profile.is_organization_admin:
            return True
            
        return False
    
    def get_accessible_teams_for_user(self, user_profile):
        """Get all teams that this workflow gives access to for the user"""
        accessible_teams = set()
        
        # Add owner team if user is member
        if user_profile in self.owner_team.members.all():
            accessible_teams.add(self.owner_team)
        
        # Add teams user has view/edit access to
        user_teams = user_profile.teams.all()
        for team in user_teams:
            if team in self.allowed_view_teams.all() or team in self.allowed_edit_teams.all():
                accessible_teams.add(team)
        
        return list(accessible_teams)
    
    def get_active_fields(self):
        """Get configuration for which fields should be shown/hidden/replaced"""
        default_config = {
            'title': {'enabled': True, 'required': True, 'replacement': None},
            'description': {'enabled': True, 'required': False, 'replacement': None},
            'priority': {'enabled': True, 'required': False, 'replacement': None},
            'tags': {'enabled': True, 'required': False, 'replacement': None},
            'due_date': {'enabled': True, 'required': False, 'replacement': None},
            'estimated_duration': {'enabled': True, 'required': False, 'replacement': None},
        }
        
        # Merge with custom configuration
        config = default_config.copy()
        if self.field_config:
            for field_name, field_settings in self.field_config.items():
                if field_name in config:
                    config[field_name].update(field_settings)
        
        return config


class WorkflowStep(models.Model):
    """Individual steps within a workflow"""
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name='steps')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Step ordering and flow
    order = models.PositiveIntegerField(help_text="Order of this step in the workflow")
    
    # Team assignment
    assigned_team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_steps')
    
    # Capacity booking requirements
    requires_booking = models.BooleanField(default=False, help_text="Does this step require capacity booking?")
    estimated_duration_hours = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Estimated time for this step")
    
    # Terminal state
    is_terminal = models.BooleanField(default=False, help_text="Is this a completion/end step?")
    
    # Custom data schema for this step (JSON)
    data_schema = models.JSONField(default=dict, blank=True, help_text="JSON schema for custom data at this step")
    
    class Meta:
        unique_together = ['workflow', 'name']
        ordering = ['workflow', 'order']
    
    def __str__(self):
        return f"{self.workflow.name} - {self.name}"


class WorkflowTransition(models.Model):
    """Define allowed transitions between workflow steps"""
    from_step = models.ForeignKey(WorkflowStep, on_delete=models.CASCADE, related_name='outgoing_transitions')
    to_step = models.ForeignKey(WorkflowStep, on_delete=models.CASCADE, related_name='incoming_transitions')
    
    # Basic properties
    label = models.CharField(max_length=100, blank=True, help_text="Optional label for this transition (e.g., 'Approve', 'Reject')")
    description = models.TextField(blank=True, help_text="Detailed description of what this transition does")
    
    # Visual customization
    COLOR_CHOICES = [
        ('blue', 'Blue (Default)'),
        ('green', 'Green (Success)'),
        ('red', 'Red (Danger/Reject)'),
        ('yellow', 'Yellow (Warning)'),
        ('purple', 'Purple (Review)'),
        ('indigo', 'Indigo (Process)'),
        ('gray', 'Gray (Neutral)'),
        ('orange', 'Orange (Alert)'),
    ]
    color = models.CharField(max_length=20, choices=COLOR_CHOICES, default='blue', help_text="Button color for this transition")
    
    ICON_CHOICES = [
        ('', 'No Icon'),
        ('fas fa-check', 'Checkmark (Approve)'),
        ('fas fa-times', 'X Mark (Reject)'),
        ('fas fa-arrow-right', 'Arrow Right (Next)'),
        ('fas fa-undo', 'Undo (Return)'),
        ('fas fa-eye', 'Eye (Review)'),
        ('fas fa-edit', 'Edit (Modify)'),
        ('fas fa-pause', 'Pause (Hold)'),
        ('fas fa-play', 'Play (Start)'),
        ('fas fa-stop', 'Stop (End)'),
        ('fas fa-upload', 'Upload (Submit)'),
        ('fas fa-download', 'Download (Retrieve)'),
        ('fas fa-cog', 'Cog (Process)'),
        ('fas fa-user', 'User (Assign)'),
        ('fas fa-users', 'Users (Team)'),
        ('fas fa-flag', 'Flag (Priority)'),
        ('fas fa-clock', 'Clock (Schedule)'),
        ('fas fa-star', 'Star (Favorite)'),
        ('fas fa-thumbs-up', 'Thumbs Up'),
        ('fas fa-thumbs-down', 'Thumbs Down'),
    ]
    icon = models.CharField(max_length=50, choices=ICON_CHOICES, blank=True, help_text="Icon to display on the transition button")
    
    # Behavioral options
    requires_confirmation = models.BooleanField(default=False, help_text="Require user confirmation before executing this transition")
    confirmation_message = models.CharField(
        max_length=200, 
        blank=True, 
        help_text="Custom confirmation message (if requires_confirmation is True)"
    )
    
    auto_assign_to_step_team = models.BooleanField(
        default=False, 
        help_text="Automatically assign work item to the destination step's assigned team"
    )
    
    requires_comment = models.BooleanField(default=False, help_text="Require a comment when using this transition")
    comment_prompt = models.CharField(
        max_length=200, 
        blank=True, 
        help_text="Custom prompt for required comment"
    )
    
    # Conditional logic and permissions
    condition = models.JSONField(default=dict, blank=True, help_text="Optional conditions for this transition")
    
    PERMISSION_CHOICES = [
        ('any', 'Any User'),
        ('assignee', 'Current Assignee Only'),
        ('team', 'Team Members Only'),
        ('admin', 'Admin/Staff Only'),
        ('creator', 'Creator Only'),
        ('custom', 'Custom Conditions'),
    ]
    permission_level = models.CharField(
        max_length=20, 
        choices=PERMISSION_CHOICES, 
        default='any',
        help_text="Who can use this transition"
    )
    
    # Ordering and display
    order = models.IntegerField(default=0, help_text="Display order for transition buttons")
    is_active = models.BooleanField(default=True, help_text="Whether this transition is available for use")
    
    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['from_step', 'to_step']
        ordering = ['order', 'label']
    
    def __str__(self):
        label_text = f" ({self.label})" if self.label else ""
        return f"{self.from_step.name} → {self.to_step.name}{label_text}"
    
    def get_button_class(self):
        """Get CSS class for transition button based on color"""
        color_classes = {
            'blue': 'bg-blue-600 hover:bg-blue-700 text-white',
            'green': 'bg-green-600 hover:bg-green-700 text-white',
            'red': 'bg-red-600 hover:bg-red-700 text-white',
            'yellow': 'bg-yellow-500 hover:bg-yellow-600 text-white',
            'purple': 'bg-purple-600 hover:bg-purple-700 text-white',
            'indigo': 'bg-indigo-600 hover:bg-indigo-700 text-white',
            'gray': 'bg-gray-600 hover:bg-gray-700 text-white',
            'orange': 'bg-orange-600 hover:bg-orange-700 text-white',
        }
        return color_classes.get(self.color, color_classes['blue'])
    
    def get_display_label(self):
        """Get the display label for the transition button"""
        return self.label or f"Move to {self.to_step.name}"
    
    def can_user_execute(self, user_profile, work_item=None):
        """Check if a user can execute this transition"""
        if not self.is_active:
            return False
            
        if self.permission_level == 'any':
            return True
        elif self.permission_level == 'assignee':
            return work_item and work_item.current_assignee == user_profile
        elif self.permission_level == 'team':
            if work_item and work_item.current_step.assigned_team:
                return user_profile in work_item.current_step.assigned_team.members.all()
            return True
        elif self.permission_level == 'admin':
            return user_profile.is_organization_admin or user_profile.has_staff_panel_access
        elif self.permission_level == 'creator':
            return work_item and work_item.created_by == user_profile
        elif self.permission_level == 'custom':
            # Implement custom condition logic here
            return self._check_custom_conditions(user_profile, work_item)
        
        return False
    
    def _check_custom_conditions(self, user_profile, work_item):
        """Check custom conditions from the condition JSON field"""
        if not self.condition:
            return True
        
        # Example condition checks - extend as needed
        conditions = self.condition
        
        # Check priority requirements
        if 'min_priority' in conditions:
            if not work_item or work_item.priority not in ['high', 'critical']:
                return False
        
        # Check role requirements
        if 'required_role' in conditions:
            # Implement role checking logic
            pass
        
        # Check time-based conditions
        if 'business_hours_only' in conditions:
            from django.utils import timezone
            now = timezone.now()
            if now.weekday() >= 5 or not (9 <= now.hour < 17):  # Weekend or outside 9-5
                return False
        
        return True
    
    def __str__(self):
        label_text = f" ({self.label})" if self.label else ""
        return f"{self.from_step.name} → {self.to_step.name}{label_text}"


class WorkItem(models.Model):
    """Individual instances of workflows - the items being processed"""
    # Unique identifier
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    # Workflow context
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name='work_items')
    current_step = models.ForeignKey(WorkflowStep, on_delete=models.PROTECT, related_name='current_work_items')
    
    # Enhanced content
    title = models.CharField(max_length=200, help_text="Human-readable identifier for this item")
    description = models.TextField(blank=True)
    rich_content = models.TextField(blank=True, help_text="Rich HTML content for detailed descriptions")
    
    # Priority and classification
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    tags = models.JSONField(default=list, help_text="List of tags for categorization")
    
    # Assignment and ownership
    created_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, related_name='created_work_items')
    current_assignee = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_work_items')
    watchers = models.ManyToManyField(UserProfile, blank=True, related_name='watched_work_items')
    
    # Dependencies
    depends_on = models.ManyToManyField('self', symmetrical=False, blank=True, related_name='dependents')
    
    # Due dates and scheduling
    due_date = models.DateTimeField(null=True, blank=True)
    estimated_duration = models.DurationField(null=True, blank=True, help_text="Estimated time to complete")
    
    # Custom data storage (JSON)
    data = models.JSONField(default=dict, help_text="Custom data specific to this work item")
    
    # Status tracking
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Step timing tracking
    current_step_entered_at = models.DateTimeField(
        null=True, 
        blank=True, 
        help_text="When this work item entered the current step"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
    
    def __str__(self):
        return f"{self.title} ({self.workflow.name})"
    
    @property
    def days_on_current_step(self):
        """Calculate how many days this work item has been on the current step"""
        if not self.current_step_entered_at:
            return None
        
        from django.utils import timezone
        delta = timezone.now() - self.current_step_entered_at
        return delta.days
    
    @property 
    def hours_on_current_step(self):
        """Calculate how many hours this work item has been on the current step"""
        if not self.current_step_entered_at:
            return None
            
        from django.utils import timezone
        delta = timezone.now() - self.current_step_entered_at
        return round(delta.total_seconds() / 3600, 1)
    
    @property
    def current_step_duration_display(self):
        """Get a human-readable display of time on current step"""
        if not self.current_step_entered_at:
            return "Unknown"
            
        from django.utils import timezone
        delta = timezone.now() - self.current_step_entered_at
        days = delta.days
        hours = round((delta.total_seconds() % 86400) / 3600)
        
        if days > 0:
            if hours > 0:
                return f"{days} day{'s' if days != 1 else ''}, {hours} hour{'s' if hours != 1 else ''}"
            else:
                return f"{days} day{'s' if days != 1 else ''}"
        elif delta.total_seconds() >= 3600:
            total_hours = round(delta.total_seconds() / 3600, 1)
            return f"{total_hours} hour{'s' if total_hours != 1 else ''}"
        else:
            minutes = round(delta.total_seconds() / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
    
    def get_available_backward_steps(self):
        """Get steps that this work item can be moved back to based on history"""
        # Get unique previous steps from history, ordered by most recent
        previous_steps = self.history.filter(
            from_step__isnull=False
        ).values_list('from_step_id', flat=True).distinct()
        
        if not previous_steps:
            return WorkflowStep.objects.none()
        
        # Return the workflow steps that were previously visited
        return WorkflowStep.objects.filter(
            id__in=previous_steps,
            workflow=self.workflow
        ).select_related('assigned_team').order_by('order')
    
    def get_backward_transitions(self, user_profile=None):
        """Get available backward transitions for this work item"""
        backward_steps = self.get_available_backward_steps()
        backward_transitions = []
        
        for step in backward_steps:
            # Create virtual backward transition
            transition_data = {
                'id': f'back_{step.id}',
                'from_step': self.current_step,
                'to_step': step,
                'label': f'Return to {step.name}',
                'description': f'Move back to the {step.name} step',
                'color': 'gray',
                'icon': 'fas fa-undo',
                'is_backward': True,
                'requires_confirmation': True,
                'confirmation_message': f'Are you sure you want to move this item back to {step.name}? This will reverse the workflow progress.',
                'requires_comment': True,
                'comment_prompt': 'Please explain why you are moving this item backward',
                'permission_level': 'admin',  # Only admins can move items backward by default
                'is_active': True
            }
            
            # Check permissions if user_profile is provided
            if user_profile:
                can_execute = (
                    user_profile.is_organization_admin or 
                    user_profile.has_staff_panel_access or
                    self.created_by == user_profile  # Creator can also move back
                )
                if not can_execute:
                    continue
            
            backward_transitions.append(type('BackwardTransition', (), transition_data)())
        
        return backward_transitions
    
    def can_move_backward(self, user_profile):
        """Check if the user can move this work item backward"""
        if not self.get_available_backward_steps().exists():
            return False
        
        # Only allow backward movement if user has appropriate permissions
        return (
            user_profile.is_organization_admin or 
            user_profile.has_staff_panel_access or
            self.created_by == user_profile
        )

    def transfer_to_workflow(self, destination_workflow, destination_step, transferred_by, notes="", preserve_assignee=False):
        """
        Transfer this work item to a different workflow while preserving history and handling bookings
        
        Args:
            destination_workflow: Target Workflow instance
            destination_step: Target WorkflowStep instance in the destination workflow
            transferred_by: UserProfile instance of the person performing the transfer
            notes: Optional notes about the transfer
            preserve_assignee: Whether to keep current assignee (if they have access to destination workflow)
        
        Returns:
            dict: Result of the transfer operation with success status and messages
        """
        from services.scheduling.models import BookingRequest
        
        # Validate inputs
        if destination_workflow == self.workflow:
            return {
                'success': False,
                'error': 'Cannot transfer work item to the same workflow',
                'messages': []
            }
        
        if destination_step.workflow != destination_workflow:
            return {
                'success': False,
                'error': 'Destination step does not belong to destination workflow',
                'messages': []
            }
        
        # Store original values for history
        old_workflow = self.workflow
        old_step = self.current_step
        old_assignee = self.current_assignee
        
        messages = []
        
        try:
            # Handle bookings first - Update CFlows bookings
            cflows_bookings = self.bookings.all()
            cflows_bookings_count = cflows_bookings.count()
            
            if cflows_bookings_count > 0:
                # Update all CFlows bookings to reference the new workflow
                updated_count = 0
                for booking in cflows_bookings:
                    # Find a suitable step in the destination workflow for booking
                    # Try to match by name first, otherwise use the destination step
                    matching_step = destination_workflow.steps.filter(
                        name__iexact=booking.workflow_step.name
                    ).first()
                    
                    if not matching_step:
                        matching_step = destination_step
                    
                    booking.workflow_step = matching_step
                    booking.save()
                    updated_count += 1
                
                messages.append(f"Updated {updated_count} CFlows booking(s) to new workflow")
            
            # Handle Scheduling service bookings
            try:
                scheduling_bookings = BookingRequest.objects.filter(
                    source_service='cflows',
                    source_object_type='WorkItem',
                    source_object_id=str(self.id),
                    organization=self.workflow.organization
                )
                scheduling_bookings_count = scheduling_bookings.count()
                
                if scheduling_bookings_count > 0:
                    # Update custom_data to reflect new workflow
                    for booking in scheduling_bookings:
                        if not booking.custom_data:
                            booking.custom_data = {}
                        
                        # Update workflow references in custom data
                        booking.custom_data.update({
                            'transferred_from_workflow': old_workflow.name,
                            'transferred_to_workflow': destination_workflow.name,
                            'transfer_date': timezone.now().isoformat(),
                            'transferred_by': transferred_by.user.username,
                            'workflow_id': destination_workflow.id,
                            'workflow_step_name': destination_step.name
                        })
                        booking.save()
                    
                    messages.append(f"Updated {scheduling_bookings_count} scheduling booking(s) metadata")
                
            except Exception as e:
                # Don't fail the transfer if scheduling service has issues
                messages.append(f"Warning: Could not update scheduling bookings: {str(e)}")
            
            # Update work item
            self.workflow = destination_workflow
            self.current_step = destination_step
            self.current_step_entered_at = timezone.now()
            
            # Handle assignee - clear if preserve_assignee is False or assignee doesn't have access
            if not preserve_assignee or not old_assignee:
                self.current_assignee = None
            else:
                # Check if old assignee has access to destination workflow
                assignee_has_access = (
                    old_assignee.is_organization_admin or
                    (destination_workflow.owner_team and 
                     old_assignee in destination_workflow.owner_team.members.all())
                )
                if not assignee_has_access:
                    self.current_assignee = None
                    messages.append(f"Cleared assignee {old_assignee.user.username} - no access to destination workflow")
            
            # Reset completion status if destination step is not terminal
            if not destination_step.is_terminal and self.is_completed:
                self.is_completed = False
                self.completed_at = None
                messages.append("Reset completion status for non-terminal destination step")
            
            self.save()
            
            # Create history entry for the transfer
            history_entry = WorkItemHistory.objects.create(
                work_item=self,
                from_step=old_step,
                to_step=destination_step,
                changed_by=transferred_by,
                notes=f"Transferred from '{old_workflow.name}' to '{destination_workflow.name}': {notes}".strip(),
                data_snapshot=self.data.copy()
            )
            
            # Add system comment about the transfer
            WorkItemComment.objects.create(
                work_item=self,
                content=f"🔄 Work item transferred from **{old_workflow.name}** → **{destination_workflow.name}**\n\n"
                       f"**From:** {old_step.name}\n"
                       f"**To:** {destination_step.name}\n"
                       f"**Transferred by:** {transferred_by.user.get_full_name() or transferred_by.user.username}\n"
                       + (f"**Notes:** {notes}" if notes else ""),
                author=transferred_by,
                is_system_comment=True
            )
            
            # Add transfer-specific data to work item
            if not self.data:
                self.data = {}
            
            transfer_history = self.data.get('transfer_history', [])
            transfer_history.append({
                'from_workflow_id': old_workflow.id,
                'from_workflow_name': old_workflow.name,
                'from_step_id': old_step.id,
                'from_step_name': old_step.name,
                'to_workflow_id': destination_workflow.id,
                'to_workflow_name': destination_workflow.name,
                'to_step_id': destination_step.id,
                'to_step_name': destination_step.name,
                'transferred_by': transferred_by.user.username,
                'transferred_at': timezone.now().isoformat(),
                'notes': notes,
                'bookings_transferred': cflows_bookings_count + (scheduling_bookings_count if 'scheduling_bookings_count' in locals() else 0)
            })
            
            self.data['transfer_history'] = transfer_history
            self.save(update_fields=['data'])
            
            primary_message = f"Work item successfully transferred from '{old_workflow.name}' to '{destination_workflow.name}'"
            messages.insert(0, primary_message)
            
            return {
                'success': True,
                'messages': messages,
                'history_entry_id': history_entry.id,
                'old_workflow': old_workflow.name,
                'new_workflow': destination_workflow.name,
                'old_step': old_step.name,
                'new_step': destination_step.name
            }
            
        except Exception as e:
            # Rollback would happen automatically due to transaction
            return {
                'success': False,
                'error': f"Transfer failed: {str(e)}",
                'messages': messages
            }
    
    def can_transfer_to_workflow(self, user_profile, destination_workflow=None):
        """
        Check if the user can transfer this work item to another workflow
        
        Args:
            user_profile: UserProfile instance to check permissions for
            destination_workflow: Optional specific workflow to check access to
        
        Returns:
            dict: Permission check result with can_transfer boolean and reasons
        """
        # Basic permission checks
        can_transfer = False
        reasons = []
        
        # Check if user has transfer permissions
        has_transfer_permission = (
            user_profile.is_organization_admin or
            user_profile.has_staff_panel_access or
            (hasattr(user_profile, 'role') and 
             user_profile.role and 
             user_profile.role.permissions.filter(codename='workitem.transfer').exists())
        )
        
        if not has_transfer_permission:
            reasons.append("User does not have work item transfer permissions")
        
        # Check if user has access to current workflow
        has_current_workflow_access = (
            user_profile.is_organization_admin or
            self.workflow.owner_team in user_profile.teams.all() or
            self.created_by == user_profile or
            self.current_assignee == user_profile
        )
        
        if not has_current_workflow_access:
            reasons.append("User does not have access to current workflow")
        
        # Check destination workflow access if specified
        if destination_workflow:
            has_destination_access = (
                user_profile.is_organization_admin or
                destination_workflow.owner_team in user_profile.teams.all()
            )
            
            if not has_destination_access:
                reasons.append(f"User does not have access to destination workflow '{destination_workflow.name}'")
        
        # Check if work item is in a state that allows transfer
        if self.is_completed:
            reasons.append("Cannot transfer completed work items")
        
        can_transfer = has_transfer_permission and has_current_workflow_access and not self.is_completed
        
        if destination_workflow:
            can_transfer = can_transfer and (
                user_profile.is_organization_admin or
                destination_workflow.owner_team in user_profile.teams.all()
            )
        
        return {
            'can_transfer': can_transfer,
            'reasons': reasons,
            'has_permission': has_transfer_permission,
            'has_current_access': has_current_workflow_access,
            'can_access_destination': destination_workflow is None or (
                user_profile.is_organization_admin or
                destination_workflow.owner_team in user_profile.teams.all()
            )
        }

    def save(self, *args, **kwargs):
        # Mark as completed if in terminal step
        if self.current_step.is_terminal and not self.is_completed:
            self.is_completed = True
            self.completed_at = timezone.now()
        elif not self.current_step.is_terminal and self.is_completed:
            self.is_completed = False
            self.completed_at = None
        
        super().save(*args, **kwargs)
    
    def get_all_bookings_summary(self):
        """Get a summary of all bookings (CFlows and Scheduling) for this work item"""
        summary = {
            'cflows_bookings': {
                'total': 0,
                'completed': 0,
                'pending': 0
            },
            'scheduling_bookings': {
                'total': 0,
                'completed': 0,
                'pending': 0
            },
            'total_bookings': 0,
            'total_completed': 0,
            'has_bookings': False
        }
        
        # Get CFlows bookings
        cflows_bookings = self.bookings.all()
        summary['cflows_bookings']['total'] = cflows_bookings.count()
        summary['cflows_bookings']['completed'] = cflows_bookings.filter(is_completed=True).count()
        summary['cflows_bookings']['pending'] = summary['cflows_bookings']['total'] - summary['cflows_bookings']['completed']
        
        # Get Scheduling service bookings
        try:
            from services.scheduling.models import BookingRequest
            scheduling_bookings = BookingRequest.objects.filter(
                source_service='cflows',
                source_object_type='WorkItem',
                source_object_id=str(self.id)
            )
            summary['scheduling_bookings']['total'] = scheduling_bookings.count()
            summary['scheduling_bookings']['completed'] = scheduling_bookings.filter(status='completed').count()
            summary['scheduling_bookings']['pending'] = summary['scheduling_bookings']['total'] - summary['scheduling_bookings']['completed']
        except ImportError:
            pass  # Scheduling service not available
        
        # Calculate totals
        summary['total_bookings'] = summary['cflows_bookings']['total'] + summary['scheduling_bookings']['total']
        summary['total_completed'] = summary['cflows_bookings']['completed'] + summary['scheduling_bookings']['completed']
        summary['has_bookings'] = summary['total_bookings'] > 0
        
        return summary
    
    def get_booking_requirements_status(self):
        """Check if current step booking requirements are met"""
        if not self.current_step or not self.current_step.requires_booking:
            return {
                'required': False,
                'met': True,
                'message': 'No booking required for current step'
            }
        
        # Check CFlows bookings for current step
        step_bookings = self.bookings.filter(workflow_step=self.current_step)
        total_bookings = step_bookings.count()
        completed_bookings = step_bookings.filter(is_completed=True).count()
        
        if total_bookings == 0:
            return {
                'required': True,
                'met': False,
                'message': 'Booking required but none created',
                'needs_creation': True
            }
        elif completed_bookings == 0:
            return {
                'required': True,
                'met': False,
                'message': f'Booking created but not completed ({total_bookings} pending)',
                'needs_completion': True
            }
        else:
            return {
                'required': True,
                'met': True,
                'message': f'All bookings completed ({completed_bookings}/{total_bookings})',
                'all_completed': True
            }


class WorkItemHistory(models.Model):
    """Track the history of work item progression through workflow"""
    work_item = models.ForeignKey(WorkItem, on_delete=models.CASCADE, related_name='history')
    
    # Step transition
    from_step = models.ForeignKey(WorkflowStep, on_delete=models.PROTECT, null=True, blank=True, related_name='history_from')
    to_step = models.ForeignKey(WorkflowStep, on_delete=models.PROTECT, related_name='history_to')
    
    # Who made the change
    changed_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True)
    
    # Optional notes about the transition
    notes = models.TextField(blank=True)
    
    # Data snapshot at time of transition
    data_snapshot = models.JSONField(default=dict)
    
    # Timestamp
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        from_text = f"from {self.from_step.name}" if self.from_step else "started"
        return f"{self.work_item.title}: {from_text} to {self.to_step.name}"


class WorkItemAttachment(models.Model):
    """File attachments for work items"""
    work_item = models.ForeignKey(WorkItem, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='cflows/attachments/%Y/%m/%d/')
    filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()
    content_type = models.CharField(max_length=100)
    
    # Metadata
    uploaded_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return f"{self.work_item.title} - {self.filename}"


class WorkItemComment(models.Model):
    """Comments and activity on work items"""
    work_item = models.ForeignKey(WorkItem, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True)
    
    # Comment content
    content = models.TextField()
    is_system_comment = models.BooleanField(default=False, help_text="Auto-generated system comment")
    
    # Threading
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')

    # Mentions
    mentioned_users = models.ManyToManyField(
        UserProfile,
        blank=True,
        related_name='mentioned_in_comments',
        help_text="Users mentioned in this comment (@username)"
    )
    mentioned_teams = models.ManyToManyField(
        Team,
        blank=True,
        related_name='mentioned_in_comments',
        help_text="Teams mentioned in this comment (@team:Team Name)"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_edited = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"Comment on {self.work_item.title} by {self.author}"

    def get_rendered_content(self):
        """Return HTML-rendered content with mentions highlighted.
        Falls back to plain content with line breaks if utilities unavailable.
        """
        try:
            from .mention_utils import render_mentions
            # Build lookup dicts for render function
            users = {u.user.username.lower(): u for u in self.mentioned_users.all()}
            teams = {t.name: t for t in self.mentioned_teams.all()}
            return render_mentions(self.content, users, teams)
        except Exception:
            # Safe fallback: basic linebreaks conversion
            from django.utils.html import conditional_escape
            from django.utils.safestring import mark_safe
            esc = conditional_escape(self.content or '')
            return mark_safe(esc.replace('\n', '<br/>'))


class WorkItemRevision(models.Model):
    """Track revisions of work items for version control"""
    work_item = models.ForeignKey(WorkItem, on_delete=models.CASCADE, related_name='revisions')
    revision_number = models.PositiveIntegerField()
    
    # Snapshot data
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    rich_content = models.TextField(blank=True)
    data = models.JSONField(default=dict)
    
    # Change tracking
    changed_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True)
    change_summary = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['work_item', 'revision_number']
        ordering = ['-revision_number']
    
    def __str__(self):
        return f"{self.work_item.title} v{self.revision_number}"


class TeamBooking(models.Model):
    """Team capacity bookings for workflow steps - CFlows specific scheduling"""
    # Booking identification
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    # Context
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='cflows_bookings')
    work_item = models.ForeignKey('WorkItem', on_delete=models.CASCADE, related_name='bookings', null=True, blank=True)
    workflow_step = models.ForeignKey('WorkflowStep', on_delete=models.CASCADE, related_name='bookings', null=True, blank=True)
    
    # Job details
    job_type = models.ForeignKey(JobType, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Scheduling
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    
    # Capacity
    required_members = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    
    # Booking management
    booked_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, related_name='created_cflows_bookings')
    assigned_members = models.ManyToManyField(UserProfile, related_name='assigned_cflows_bookings', blank=True)
    
    # Status
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='completed_cflows_bookings')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['start_time']
    
    def __str__(self):
        return f"{self.team.name}: {self.title} ({self.start_time.strftime('%Y-%m-%d %H:%M')})"
    
    def to_scheduling_service_data(self):
        """Convert this CFlows booking to data for creating a scheduling service booking"""
        return {
            'title': self.title,
            'description': self.description or f"CFlows booking: {self.title}",
            'requested_start': self.start_time,
            'requested_end': self.end_time,
            'required_capacity': self.required_members,
            'priority': self.work_item.priority if self.work_item else 'normal',
            'source_service': 'cflows',
            'source_object_type': 'TeamBooking',
            'source_object_id': str(self.id),
            'custom_data': {
                'cflows_booking_id': self.id,
                'team_name': self.team.name,
                'work_item_id': self.work_item.id if self.work_item else None,
                'work_item_title': self.work_item.title if self.work_item else None,
                'workflow_step': self.workflow_step.name if self.workflow_step else None,
                'job_type': self.job_type.name if self.job_type else None
            }
        }
    
    def sync_to_scheduling_service(self):
        """Create or update a corresponding booking in the scheduling service"""
        try:
            from services.scheduling.models import BookingRequest, SchedulableResource
            
            # Check if already synced
            existing_booking = BookingRequest.objects.filter(
                source_service='cflows',
                source_object_type='TeamBooking',
                source_object_id=str(self.id)
            ).first()
            
            if existing_booking:
                # Update existing booking
                data = self.to_scheduling_service_data()
                for key, value in data.items():
                    if key not in ['source_service', 'source_object_type', 'source_object_id']:
                        setattr(existing_booking, key, value)
                existing_booking.save()
                return existing_booking
            else:
                # Find or create a corresponding resource
                resource = SchedulableResource.objects.filter(
                    linked_team=self.team,
                    organization=self.team.organization
                ).first()
                
                if not resource:
                    # Create a resource for this team if it doesn't exist
                    resource = SchedulableResource.objects.create(
                        organization=self.team.organization,
                        name=f"{self.team.name} (Auto-created)",
                        resource_type='team',
                        description=f"Auto-created resource for team {self.team.name}",
                        linked_team=self.team,
                        service_type='cflows'
                    )
                
                # Create new booking
                data = self.to_scheduling_service_data()
                booking = BookingRequest.objects.create(
                    organization=self.team.organization,
                    resource=resource,
                    requested_by=self.booked_by,
                    **data
                )
                return booking
                
        except ImportError:
            # Scheduling service not available
            return None
        except Exception as e:
            # Log error but don't break the application
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error syncing booking {self.id} to scheduling service: {str(e)}")
            return None


class CustomField(models.Model):
    """Custom fields that organizations can define for their work items"""
    
    FIELD_TYPES = [
        ('text', 'Text Input'),
        ('textarea', 'Text Area'), 
        ('number', 'Number'),
        ('decimal', 'Decimal'),
        ('date', 'Date'),
        ('datetime', 'Date & Time'),
        ('checkbox', 'Checkbox'),
        ('select', 'Dropdown Select'),
        ('multiselect', 'Multiple Select'),
        ('email', 'Email'),
        ('url', 'URL'),
        ('phone', 'Phone Number'),
    ]
    
    # Basic field definition
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='custom_fields')
    name = models.CharField(max_length=100, help_text="Internal field name (no spaces)")
    label = models.CharField(max_length=200, help_text="Display label for users")
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES, default='text')
    
    # Field configuration
    is_required = models.BooleanField(default=False)
    default_value = models.TextField(blank=True, help_text="Default value (JSON for complex types)")
    help_text = models.CharField(max_length=500, blank=True, help_text="Help text shown to users")
    placeholder = models.CharField(max_length=200, blank=True, help_text="Placeholder text for input fields")
    
    # Validation
    min_length = models.PositiveIntegerField(null=True, blank=True, help_text="Minimum length for text fields")
    max_length = models.PositiveIntegerField(null=True, blank=True, help_text="Maximum length for text fields")
    min_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Minimum value for number fields")
    max_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Maximum value for number fields")
    
    # Select field options (JSON array)
    options = models.JSONField(default=list, blank=True, help_text="Options for select fields (JSON array)")
    
    # Field ordering and organization
    order = models.PositiveIntegerField(default=0, help_text="Display order")
    section = models.CharField(max_length=100, blank=True, help_text="Section to group fields")
    
    # Workflow context - optional workflow filtering
    workflows = models.ManyToManyField(Workflow, blank=True, help_text="Limit to specific workflows (empty = all workflows)")
    workflow_steps = models.ManyToManyField(WorkflowStep, blank=True, help_text="Show only for specific steps")
    
    # Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['section', 'order', 'label']
        unique_together = ['organization', 'name']
    
    def __str__(self):
        return f"{self.organization.name} - {self.label}"
    
    def get_form_field(self):
        """Generate Django form field based on field type"""
        from django import forms
        
        field_class = forms.CharField
        widget_attrs = {
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500'
        }
        
        if self.placeholder:
            widget_attrs['placeholder'] = self.placeholder
        
        field_kwargs = {
            'label': self.label,
            'required': self.is_required,
            'help_text': self.help_text,
        }
        
        if self.field_type == 'text':
            if self.max_length:
                field_kwargs['max_length'] = self.max_length
            if self.min_length:
                field_kwargs['min_length'] = self.min_length
            field_class = forms.CharField
            widget_attrs.update({'type': 'text'})
            
        elif self.field_type == 'textarea':
            field_class = forms.CharField
            widget_attrs.update({'rows': '4'})
            field_kwargs['widget'] = forms.Textarea(attrs=widget_attrs)
            
        elif self.field_type == 'number':
            field_class = forms.IntegerField
            widget_attrs.update({'type': 'number'})
            if self.min_value is not None:
                field_kwargs['min_value'] = int(self.min_value)
            if self.max_value is not None:
                field_kwargs['max_value'] = int(self.max_value)
                
        elif self.field_type == 'decimal':
            field_class = forms.DecimalField
            widget_attrs.update({'type': 'number', 'step': '0.01'})
            if self.min_value is not None:
                field_kwargs['min_value'] = self.min_value
            if self.max_value is not None:
                field_kwargs['max_value'] = self.max_value
                
        elif self.field_type == 'date':
            field_class = forms.DateField
            widget_attrs.update({'type': 'date'})
            
        elif self.field_type == 'datetime':
            field_class = forms.DateTimeField
            widget_attrs.update({'type': 'datetime-local'})
            
        elif self.field_type == 'checkbox':
            field_class = forms.BooleanField
            widget_attrs = {'class': 'rounded text-purple-600 focus:ring-purple-500'}
            field_kwargs['widget'] = forms.CheckboxInput(attrs=widget_attrs)
            
        elif self.field_type == 'select':
            field_class = forms.ChoiceField
            choices = [(opt, opt) for opt in self.options] if self.options else []
            field_kwargs['choices'] = [('', '-- Select --')] + choices
            field_kwargs['widget'] = forms.Select(attrs=widget_attrs)
            
        elif self.field_type == 'multiselect':
            field_class = forms.MultipleChoiceField
            choices = [(opt, opt) for opt in self.options] if self.options else []
            field_kwargs['choices'] = choices
            widget_attrs.update({'multiple': True, 'size': min(len(choices), 5)})
            field_kwargs['widget'] = forms.SelectMultiple(attrs=widget_attrs)
            
        elif self.field_type == 'email':
            field_class = forms.EmailField
            widget_attrs.update({'type': 'email'})
            
        elif self.field_type == 'url':
            field_class = forms.URLField
            widget_attrs.update({'type': 'url'})
            
        elif self.field_type == 'phone':
            field_class = forms.CharField
            widget_attrs.update({'type': 'tel'})
        
        # Set default widget if not already set
        if 'widget' not in field_kwargs:
            if self.field_type == 'checkbox':
                pass  # Already set above
            else:
                field_kwargs['widget'] = forms.TextInput(attrs=widget_attrs) if field_class == forms.CharField else None
        
        # Set default value
        if self.default_value and self.field_type != 'checkbox':
            field_kwargs['initial'] = self.default_value
        elif self.field_type == 'checkbox' and self.default_value:
            field_kwargs['initial'] = self.default_value.lower() in ['true', '1', 'yes']
        
        return field_class(**field_kwargs)


class WorkItemCustomFieldValue(models.Model):
    """Values for custom fields on work items"""
    
    work_item = models.ForeignKey(WorkItem, on_delete=models.CASCADE, related_name='custom_field_values')
    custom_field = models.ForeignKey(CustomField, on_delete=models.CASCADE)
    workflow_step = models.ForeignKey(WorkflowStep, on_delete=models.CASCADE, null=True, blank=True, help_text="Step where this data was collected")
    
    # Store value as text - will be converted based on field type
    value = models.TextField(blank=True)
    
    # Track when this was collected
    collected_by = models.ForeignKey('core.UserProfile', on_delete=models.SET_NULL, null=True, help_text="User who provided this data")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['work_item', 'custom_field']
    
    def __str__(self):
        return f"{self.work_item.title} - {self.custom_field.label}: {self.value[:50]}"
    
    def get_display_value(self):
        """Get formatted value for display"""
        if not self.value:
            return ''
            
        field_type = self.custom_field.field_type
        
        if field_type == 'checkbox':
            return 'Yes' if self.value.lower() in ['true', '1', 'yes'] else 'No'
        elif field_type in ['date', 'datetime']:
            try:
                from django.utils import timezone
                if field_type == 'date':
                    date_obj = timezone.datetime.strptime(self.value, '%Y-%m-%d').date()
                    return date_obj.strftime('%B %d, %Y')
                else:
                    datetime_obj = timezone.datetime.fromisoformat(self.value.replace('Z', '+00:00'))
                    return datetime_obj.strftime('%B %d, %Y at %I:%M %p')
            except (ValueError, AttributeError):
                return self.value
        elif field_type == 'multiselect':
            try:
                import json
                values = json.loads(self.value) if isinstance(self.value, str) else self.value
                return ', '.join(values) if isinstance(values, list) else str(values)
            except (json.JSONDecodeError, TypeError):
                return self.value
        else:
            return self.value
    
    def set_value(self, value):
        """Set value with proper formatting"""
        if self.custom_field.field_type == 'multiselect' and isinstance(value, list):
            import json
            self.value = json.dumps(value)
        elif self.custom_field.field_type == 'checkbox':
            self.value = str(bool(value)).lower()
        else:
            self.value = str(value) if value is not None else ''


class StepDataCollection(models.Model):
    """Tracks when a work item needs custom data collection for a step"""
    
    work_item = models.ForeignKey(WorkItem, on_delete=models.CASCADE, related_name='step_data_collections')
    workflow_step = models.ForeignKey(WorkflowStep, on_delete=models.CASCADE)
    
    # Status of data collection
    is_completed = models.BooleanField(default=False)
    completed_by = models.ForeignKey('core.UserProfile', on_delete=models.SET_NULL, null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Track when this was initiated
    initiated_by = models.ForeignKey('core.UserProfile', on_delete=models.SET_NULL, null=True, related_name='initiated_data_collections')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['work_item', 'workflow_step']
    
    def __str__(self):
        return f"{self.work_item.title} - {self.workflow_step.name} data collection"
    
    def get_required_fields(self):
        """Get required custom fields for this step"""
        return self.workflow_step.custom_fields.filter(is_required=True)
    
    def get_optional_fields(self):
        """Get optional custom fields for this step"""
        return self.workflow_step.custom_fields.filter(is_required=False)
    
    def has_all_required_data(self):
        """Check if all required fields have been filled"""
        required_fields = self.get_required_fields()
        for field in required_fields:
            try:
                value = WorkItemCustomFieldValue.objects.get(
                    work_item=self.work_item,
                    custom_field=field
                )
                if not value.value:  # Empty values count as missing
                    return False
            except WorkItemCustomFieldValue.DoesNotExist:
                return False
        return True


class CalendarView(models.Model):
    """Saved calendar filter views for users"""
    name = models.CharField(max_length=100)
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='saved_calendar_views')
    is_default = models.BooleanField(default=False)
    
    # Filter settings (stored as JSON)
    teams = models.JSONField(default=list, blank=True)  # List of team IDs
    job_types = models.JSONField(default=list, blank=True)  # List of job type IDs
    workflows = models.JSONField(default=list, blank=True)  # List of workflow IDs
    status = models.CharField(max_length=20, blank=True)
    event_type = models.CharField(max_length=20, blank=True)
    booked_by = models.CharField(max_length=10, blank=True)  # User ID as string
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'name']
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.user})"
    
    def save(self, *args, **kwargs):
        # If this is being set as default, unset other defaults for this user
        if self.is_default:
            CalendarView.objects.filter(user=self.user, is_default=True).update(is_default=False)
        super().save(*args, **kwargs)


class WorkItemFilterView(models.Model):
    """Saved work item filter views for users"""
    name = models.CharField(max_length=100)
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='saved_work_item_filter_views')
    is_default = models.BooleanField(default=False)
    
    # Filter settings (stored as JSON to match the current filter structure)
    workflow = models.CharField(max_length=20, blank=True)  # Workflow ID as string
    assignee = models.CharField(max_length=20, blank=True)  # Assignee ID as string
    priority = models.CharField(max_length=20, blank=True)  # Priority value
    status = models.CharField(max_length=20, blank=True)  # Status value (active/completed)
    search = models.CharField(max_length=200, blank=True)  # Search term
    sort = models.CharField(max_length=50, default='-updated_at')  # Sort field
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'name']
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.user})"
    
    def save(self, *args, **kwargs):
        # If this is being set as default, unset other defaults for this user
        if self.is_default:
            WorkItemFilterView.objects.filter(user=self.user, is_default=True).update(is_default=False)
        super().save(*args, **kwargs)
    
    def to_filter_dict(self):
        """Convert saved filter to dictionary format used by the view"""
        return {
            'workflow': self.workflow,
            'assignee': self.assignee,
            'priority': self.priority,
            'status': self.status,
            'search': self.search,
            'sort': self.sort,
        }
    
    @classmethod
    def from_request_params(cls, params):
        """Create filter data from request parameters"""
        return {
            'workflow': params.get('workflow', ''),
            'assignee': params.get('assignee', ''),
            'priority': params.get('priority', ''),
            'status': params.get('status', ''),
            'search': params.get('search', ''),
            'sort': params.get('sort', '-updated_at'),
        }
