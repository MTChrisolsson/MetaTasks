from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.db import models
from core.models import Organization, UserProfile, Team, JobType
from .models import (
    Workflow, WorkflowStep, WorkflowTransition, WorkflowTemplate,
    WorkItem, WorkItemComment, WorkItemAttachment, TeamBooking,
    CustomField, WorkItemFilterView
)
import json


class WorkflowForm(forms.ModelForm):
    """Form for creating and editing workflows"""
    
    class Meta:
        model = Workflow
        fields = [
            'name', 'description', 'parent_workflow', 'template', 'is_shared', 
            'auto_assign', 'requires_approval', 'owner_team',
            'allowed_view_teams', 'allowed_edit_teams'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Enter workflow name'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Describe this workflow...',
                'rows': 3
            }),
            'parent_workflow': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500'
            }),
            'template': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500'
            }),
            'is_shared': forms.CheckboxInput(attrs={
                'class': 'rounded text-purple-600 focus:ring-purple-500'
            }),
            'auto_assign': forms.CheckboxInput(attrs={
                'class': 'rounded text-purple-600 focus:ring-purple-500'
            }),
            'requires_approval': forms.CheckboxInput(attrs={
                'class': 'rounded text-purple-600 focus:ring-purple-500'
            }),
            'owner_team': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500'
            }),
            'allowed_view_teams': forms.SelectMultiple(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'size': '4'
            }),
            'allowed_edit_teams': forms.SelectMultiple(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'size': '4'
            }),
        }

    def __init__(self, *args, organization=None, user_profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.user_profile = user_profile
        
        if organization:
            # Filter templates available to this organization
            self.fields['template'].queryset = WorkflowTemplate.objects.filter(
                models.Q(is_public=True) | models.Q(created_by_org=organization)
            )
            
            # Filter parent workflows to only those in the organization (exclude self if editing)
            parent_workflows = Workflow.objects.filter(organization=organization)
            if self.instance and self.instance.pk:
                # Exclude self and any descendants to prevent circular references
                descendants = self.instance.get_all_sub_workflows(include_self=True)
                descendant_ids = [w.id for w in descendants]
                parent_workflows = parent_workflows.exclude(id__in=descendant_ids)
            
            # Create hierarchical choices for parent workflows
            parent_choices = [('', 'No parent workflow (top-level)')]
            for workflow in parent_workflows.filter(parent_workflow__isnull=True):
                parent_choices.append((workflow.id, workflow.name))
                for sub_workflow in workflow.sub_workflows.all():
                    parent_choices.append((sub_workflow.id, f"{workflow.name} > {sub_workflow.name}"))
            
            self.fields['parent_workflow'].choices = parent_choices
            
            # Filter teams to only those in the organization
            organization_teams = Team.objects.filter(organization=organization)
            self.fields['owner_team'].queryset = organization_teams
            self.fields['allowed_view_teams'].queryset = organization_teams
            self.fields['allowed_edit_teams'].queryset = organization_teams
            
            # Set required field
            self.fields['owner_team'].required = True
            
    def clean_owner_team(self):
        """Validate owner team selection"""
        owner_team = self.cleaned_data.get('owner_team')
        if not owner_team:
            raise ValidationError("Owner team is required")
        
        # Check if user has permission to set this team as owner
        if self.user_profile and not self.user_profile.is_organization_admin:
            user_teams = self.user_profile.teams.all()
            if owner_team not in user_teams:
                raise ValidationError("You can only set teams you belong to as the owner")
        
        return owner_team
        
class WorkflowStepForm(forms.ModelForm):
    """Form for creating and editing workflow steps"""
    
    class Meta:
        model = WorkflowStep
        fields = [
            'name', 'description', 'order', 'assigned_team',
            'requires_booking', 'estimated_duration_hours', 'is_terminal'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Step name'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Step description...',
                'rows': 2
            }),
            'order': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'min': '1'
            }),
            'assigned_team': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500'
            }),
            'estimated_duration_hours': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'step': '0.25',
                'min': '0'
            }),
            'requires_booking': forms.CheckboxInput(attrs={
                'class': 'rounded text-purple-600 focus:ring-purple-500'
            }),
            'is_terminal': forms.CheckboxInput(attrs={
                'class': 'rounded text-purple-600 focus:ring-purple-500'
            }),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields['assigned_team'].queryset = Team.objects.filter(
                organization=organization, is_active=True
            )


class WorkflowFieldConfigForm(forms.Form):
    """Form for configuring which standard fields to show/hide/replace in work items"""
    
    # Standard fields that can be configured
    STANDARD_FIELDS = [
        ('title', 'Title'),
        ('description', 'Description'),
        ('priority', 'Priority'),
        ('tags', 'Tags'),
        ('due_date', 'Due Date'),
        ('estimated_duration', 'Estimated Duration'),
    ]
    
    def __init__(self, *args, workflow=None, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.workflow = workflow
        self.organization = organization
        
        # Get available custom fields for replacement options
        custom_fields = []
        if organization:
            custom_fields = CustomField.objects.filter(organization=organization)
        
        # Generate fields for each standard field
        for field_name, field_label in self.STANDARD_FIELDS:
            # Enable/disable checkbox
            self.fields[f'{field_name}_enabled'] = forms.BooleanField(
                required=False,
                label=f'Show {field_label}',
                widget=forms.CheckboxInput(attrs={
                    'class': 'rounded text-indigo-600 focus:ring-indigo-500'
                }),
                initial=True
            )
            
            # Required checkbox
            self.fields[f'{field_name}_required'] = forms.BooleanField(
                required=False,
                label=f'{field_label} Required',
                widget=forms.CheckboxInput(attrs={
                    'class': 'rounded text-red-600 focus:ring-red-500'
                }),
                initial=(field_name == 'title')  # Title is required by default
            )
            
            # Replacement dropdown
            replacement_choices = [('', 'Use standard field')] + [
                (cf.id, f'Replace with: {cf.name}') for cf in custom_fields
            ]
            self.fields[f'{field_name}_replacement'] = forms.ChoiceField(
                choices=replacement_choices,
                required=False,
                label=f'Replace {field_label}',
                widget=forms.Select(attrs={
                    'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500'
                })
            )
        
        # Load existing configuration
        if workflow and workflow.field_config:
            self._load_existing_config()
    
    def _load_existing_config(self):
        """Load existing field configuration into form"""
        config = self.workflow.get_active_fields()
        
        for field_name, _ in self.STANDARD_FIELDS:
            if field_name in config:
                field_config = config[field_name]
                self.fields[f'{field_name}_enabled'].initial = field_config.get('enabled', True)
                self.fields[f'{field_name}_required'].initial = field_config.get('required', False)
                self.fields[f'{field_name}_replacement'].initial = field_config.get('replacement') or ''
    
    def save_config(self):
        """Save the field configuration to the workflow"""
        if not self.workflow:
            return
        
        config = {}
        for field_name, _ in self.STANDARD_FIELDS:
            config[field_name] = {
                'enabled': self.cleaned_data.get(f'{field_name}_enabled', True),
                'required': self.cleaned_data.get(f'{field_name}_required', False),
                'replacement': self.cleaned_data.get(f'{field_name}_replacement') or None,
            }
        
        self.workflow.field_config = config
        self.workflow.save(update_fields=['field_config'])
        
        return config


class WorkItemForm(forms.ModelForm):
    """Form for creating and editing work items"""
    
    class Meta:
        model = WorkItem
        fields = [
            'title', 'description', 'rich_content', 'priority',
            'current_assignee', 'due_date', 'estimated_duration'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Work item title'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Brief description...',
                'rows': 3
            }),
            'rich_content': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Detailed content (supports HTML)...',
                'rows': 6,
                'id': 'rich-content-editor'
            }),
            'priority': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500'
            }),
            'current_assignee': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500'
            }),
            'due_date': forms.DateTimeInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'type': 'datetime-local'
            }),
            'estimated_duration': forms.TimeInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'HH:MM:SS'
            }),
        }

    tags_input = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
            'placeholder': 'Enter tags separated by commas',
            'data-tags-input': 'true'
        }),
        help_text='Enter tags separated by commas'
    )

    def __init__(self, *args, organization=None, workflow=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Store workflow reference for field replacement logic
        self.workflow = workflow
        self.organization = organization
        
        # Apply workflow field configuration
        if workflow:
            field_config = workflow.get_active_fields()
            self._apply_field_configuration(field_config)
        
        if organization:
            # Filter assignees to organization members
            self.fields['current_assignee'].queryset = UserProfile.objects.filter(
                organization=organization, user__is_active=True
            )
        
        # Handle tags display
        if self.instance and self.instance.pk:
            if 'tags_input' in self.fields:  # Only if tags are enabled
                self.fields['tags_input'].initial = ', '.join(self.instance.tags)
        
        # Add custom fields for this organization
        if organization:
            from .models import CustomField
            custom_fields = CustomField.objects.filter(
                organization=organization,
                is_active=True
            )
            
            # Filter by workflow if provided
            if workflow:
                custom_fields = custom_fields.filter(
                    models.Q(workflows__isnull=True) | models.Q(workflows=workflow)
                )
            
            # Sort by section and order
            custom_fields = custom_fields.order_by('section', 'order', 'label')
            
            # Add each custom field to the form
            for custom_field in custom_fields:
                field_name = f'custom_{custom_field.id}'
                self.fields[field_name] = custom_field.get_form_field()
                
                # Set initial value if editing existing work item
                if self.instance and self.instance.pk:
                    try:
                        from .models import WorkItemCustomFieldValue
                        custom_value = WorkItemCustomFieldValue.objects.get(
                            work_item=self.instance,
                            custom_field=custom_field
                        )
                        if custom_field.field_type == 'checkbox':
                            self.fields[field_name].initial = custom_value.value.lower() in ['true', '1', 'yes']
                        elif custom_field.field_type == 'multiselect':
                            import json
                            try:
                                self.fields[field_name].initial = json.loads(custom_value.value)
                            except json.JSONDecodeError:
                                self.fields[field_name].initial = []
                        else:
                            self.fields[field_name].initial = custom_value.value
                    except WorkItemCustomFieldValue.DoesNotExist:
                        pass

    def _apply_field_configuration(self, field_config):
        """Apply workflow field configuration to the form"""
        # Map of form field names to config keys
        field_mapping = {
            'title': 'title',
            'description': 'description', 
            'priority': 'priority',
            'due_date': 'due_date',
            'estimated_duration': 'estimated_duration'
        }
        
        # Handle tags separately since it's a custom field
        if not field_config.get('tags', {}).get('enabled', True):
            if 'tags_input' in self.fields:
                del self.fields['tags_input']
        elif field_config.get('tags', {}).get('required', False):
            if 'tags_input' in self.fields:
                self.fields['tags_input'].required = True
                # Update the widget to show required indicator
                current_attrs = self.fields['tags_input'].widget.attrs.copy()
                current_attrs['required'] = True
                self.fields['tags_input'].widget.attrs = current_attrs
        
        # Apply configuration to standard fields
        for form_field, config_key in field_mapping.items():
            field_settings = field_config.get(config_key, {})
            
            # Remove field if disabled
            if not field_settings.get('enabled', True):
                if form_field in self.fields:
                    del self.fields[form_field]
                continue
            
            # Make field required if configured
            if field_settings.get('required', False):
                if form_field in self.fields:
                    self.fields[form_field].required = True
                    # Update the widget to show required indicator
                    current_attrs = self.fields[form_field].widget.attrs.copy()
                    current_attrs['required'] = True
                    self.fields[form_field].widget.attrs = current_attrs
            
            # Handle field replacement with custom fields
            replacement_id = field_settings.get('replacement')
            if replacement_id:
                try:
                    from .models import CustomField
                    replacement_field = CustomField.objects.get(id=replacement_id, organization=self.workflow.organization)
                    
                    # Remove the standard field
                    if form_field in self.fields:
                        del self.fields[form_field]
                    
                    # Add the replacement custom field
                    replacement_field_name = f'replacement_{form_field}'
                    self.fields[replacement_field_name] = replacement_field.get_form_field()
                    
                    # Store mapping for save logic
                    if not hasattr(self, '_field_replacements'):
                        self._field_replacements = {}
                    self._field_replacements[form_field] = {
                        'custom_field_id': replacement_id,
                        'field_name': replacement_field_name
                    }
                    
                except CustomField.DoesNotExist:
                    # If replacement field doesn't exist, just continue with standard field
                    pass

    def clean_tags_input(self):
        tags_input = self.cleaned_data.get('tags_input', '')
        if tags_input:
            # Handle both string and list inputs
            if isinstance(tags_input, list):
                return tags_input
            elif isinstance(tags_input, str):
                tags = [tag.strip() for tag in tags_input.split(',') if tag.strip()]
                return tags
        return []

    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Handle tags from tags_input
        if 'tags_input' in self.cleaned_data:
            tags_data = self.clean_tags_input()
            instance.tags = tags_data
        
        # Handle field replacements - CRITICAL: Transfer replacement values to actual work item fields
        if hasattr(self, '_field_replacements'):
            for standard_field, replacement_info in self._field_replacements.items():
                field_name = replacement_info['field_name']
                if field_name in self.cleaned_data:
                    replacement_value = self.cleaned_data[field_name]
                    
                    # Transfer the replacement value to the actual work item field
                    if standard_field == 'title' and replacement_value:
                        instance.title = str(replacement_value)
                    elif standard_field == 'description' and replacement_value:
                        instance.description = str(replacement_value)
                    elif standard_field == 'priority' and replacement_value:
                        instance.priority = str(replacement_value)
                    elif standard_field == 'due_date' and replacement_value:
                        instance.due_date = replacement_value
                    elif standard_field == 'estimated_duration' and replacement_value:
                        instance.estimated_duration = replacement_value
                    
                    # Also store replacement metadata in the work item's data field for reference
                    if not instance.data:
                        instance.data = {}
                    instance.data[f'replacement_{standard_field}'] = {
                        'custom_field_id': replacement_info['custom_field_id'],
                        'value': str(replacement_value)
                    }
        
        if commit:
            instance.save()
            # Save custom field values and replacement field values
            self.save_custom_fields(instance)
        
        return instance
    
    def save_custom_fields(self, work_item):
        """Save custom field values for the work item"""
        from .models import CustomField, WorkItemCustomFieldValue
        
        for field_name, value in self.cleaned_data.items():
            if field_name.startswith('custom_'):
                try:
                    custom_field_id = int(field_name.replace('custom_', ''))
                    custom_field = CustomField.objects.get(id=custom_field_id)
                    
                    # Get or create the custom field value
                    custom_value, created = WorkItemCustomFieldValue.objects.get_or_create(
                        work_item=work_item,
                        custom_field=custom_field
                    )
                    
                    # Set the value based on field type
                    custom_value.set_value(value)
                    custom_value.save()
                    
                except (ValueError, CustomField.DoesNotExist):
                    continue
            
            elif field_name.startswith('replacement_'):
                # Handle replacement fields that should be saved as custom field values
                if hasattr(self, '_field_replacements'):
                    # Find the replacement mapping
                    standard_field = field_name.replace('replacement_', '')
                    if standard_field in self._field_replacements:
                        replacement_info = self._field_replacements[standard_field]
                        custom_field_id = replacement_info['custom_field_id']
                        
                        try:
                            custom_field = CustomField.objects.get(id=custom_field_id)
                            
                            # Get or create the custom field value
                            custom_value, created = WorkItemCustomFieldValue.objects.get_or_create(
                                work_item=work_item,
                                custom_field=custom_field
                            )
                            
                            # Set the value based on field type
                            custom_value.set_value(value)
                            custom_value.save()
                            
                        except CustomField.DoesNotExist:
                            continue


class WorkItemCommentForm(forms.ModelForm):
    """Form for adding comments to work items"""
    
    class Meta:
        model = WorkItemComment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Add a comment...',
                'rows': 3
            })
        }


class WorkItemAttachmentForm(forms.ModelForm):
    """Form for uploading attachments to work items"""
    
    class Meta:
        model = WorkItemAttachment
        fields = ['file', 'description']
        widgets = {
            'file': forms.FileInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'accept': '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.jpg,.jpeg,.png,.gif,.zip,.rar'
            }),
            'description': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Optional description...'
            })
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.file:
            instance.filename = instance.file.name
            instance.file_size = instance.file.size
            instance.content_type = instance.file.content_type or 'application/octet-stream'
        if commit:
            instance.save()
        return instance


class WorkflowTransitionForm(forms.ModelForm):
    """Enhanced form for creating and customizing workflow transitions"""
    
    class Meta:
        model = WorkflowTransition
        fields = [
            'to_step', 'label', 'description', 'color', 'icon',
            'requires_confirmation', 'confirmation_message', 'requires_comment', 'comment_prompt',
            'auto_assign_to_step_team', 'permission_level', 'order', 'is_active'
        ]
        widgets = {
            'to_step': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500'
            }),
            'label': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
                'placeholder': 'e.g., "Approve", "Reject", "Send for Review"'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
                'rows': 3,
                'placeholder': 'Detailed description of what this transition does...'
            }),
            'color': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500'
            }),
            'icon': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500'
            }),
            'requires_confirmation': forms.CheckboxInput(attrs={
                'class': 'rounded text-indigo-600 focus:ring-indigo-500'
            }),
            'confirmation_message': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
                'placeholder': 'Are you sure you want to approve this item?'
            }),
            'requires_comment': forms.CheckboxInput(attrs={
                'class': 'rounded text-indigo-600 focus:ring-indigo-500'
            }),
            'comment_prompt': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
                'placeholder': 'Please provide a reason for this decision'
            }),
            'auto_assign_to_step_team': forms.CheckboxInput(attrs={
                'class': 'rounded text-indigo-600 focus:ring-indigo-500'
            }),
            'permission_level': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500'
            }),
            'order': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
                'min': '0',
                'step': '1'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'rounded text-indigo-600 focus:ring-indigo-500'
            }),
        }
        help_texts = {
            'label': 'Display name for the transition button (e.g., "Approve", "Reject")',
            'description': 'Detailed explanation of what happens when this transition is used',
            'color': 'Visual color theme for the transition button',
            'icon': 'Optional icon to display alongside the transition label',
            'requires_confirmation': 'Ask user to confirm before executing this transition',
            'confirmation_message': 'Custom message for confirmation dialog (if confirmation required)',
            'requires_comment': 'Force user to add a comment when using this transition',
            'comment_prompt': 'Custom prompt text for the required comment field',
            'auto_assign_to_step_team': 'Automatically assign work item to destination step\'s team',
            'permission_level': 'Control who can use this transition',
            'order': 'Display order for transition buttons (lower numbers appear first)',
            'is_active': 'Whether this transition is currently available for use',
        }

    def __init__(self, *args, workflow=None, from_step=None, **kwargs):
        super().__init__(*args, **kwargs)
        if workflow:
            # Only show steps from the same workflow, excluding the from_step
            steps = WorkflowStep.objects.filter(workflow=workflow).order_by('order')
            if from_step:
                steps = steps.exclude(id=from_step.id)
            self.fields['to_step'].queryset = steps
            
            # Improve field labels and help text
            self.fields['to_step'].label = 'Destination Step'
            self.fields['to_step'].help_text = 'Select the step this transition leads to'
        
        if from_step:
            self.from_step = from_step
        
        # Add conditional field display logic
        self.fields['confirmation_message'].widget.attrs['data-depends'] = 'id_requires_confirmation'
        self.fields['comment_prompt'].widget.attrs['data-depends'] = 'id_requires_comment'

    def clean(self):
        cleaned_data = super().clean()
        to_step = cleaned_data.get('to_step')
        requires_confirmation = cleaned_data.get('requires_confirmation')
        confirmation_message = cleaned_data.get('confirmation_message')
        requires_comment = cleaned_data.get('requires_comment')
        comment_prompt = cleaned_data.get('comment_prompt')
        
        # Validate transition uniqueness
        if hasattr(self, 'from_step') and to_step:
            existing = WorkflowTransition.objects.filter(
                from_step=self.from_step,
                to_step=to_step
            )
            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            
            if existing.exists():
                raise ValidationError('A transition from this step to the selected step already exists.')
        
        # Validate confirmation message
        if requires_confirmation and not confirmation_message:
            self.add_error('confirmation_message', 'Confirmation message is required when confirmation is enabled.')
        
        # Validate comment prompt
        if requires_comment and not comment_prompt:
            self.add_error('comment_prompt', 'Comment prompt is required when comments are required.')
        
        return cleaned_data


class BulkTransitionForm(forms.Form):
    """Form for creating multiple transitions at once"""
    
    TRANSITION_TYPES = [
        ('sequential', 'Sequential Flow (Step 1 → Step 2 → Step 3...)'),
        ('hub_spoke', 'Hub and Spoke (All steps ↔ Central step)'),
        ('parallel', 'Parallel Branches (One step → Multiple steps)'),
        ('custom', 'Custom Selection'),
    ]
    
    transition_type = forms.ChoiceField(
        choices=TRANSITION_TYPES,
        widget=forms.RadioSelect(attrs={
            'class': 'text-indigo-600 focus:ring-indigo-500'
        }),
        help_text='Choose a pattern for creating multiple transitions'
    )
    
    central_step = forms.ModelChoiceField(
        queryset=WorkflowStep.objects.none(),
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500'
        }),
        help_text='For hub and spoke pattern, select the central step'
    )
    
    source_step = forms.ModelChoiceField(
        queryset=WorkflowStep.objects.none(),
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500'
        }),
        help_text='For parallel branches, select the source step'
    )
    
    target_steps = forms.ModelMultipleChoiceField(
        queryset=WorkflowStep.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'text-indigo-600 focus:ring-indigo-500'
        }),
        help_text='For parallel branches, select target steps'
    )
    
    # Custom selection fields
    custom_transitions = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
        help_text='JSON data for custom transitions'
    )
    
    def __init__(self, *args, workflow=None, **kwargs):
        super().__init__(*args, **kwargs)
        if workflow:
            steps = WorkflowStep.objects.filter(workflow=workflow).order_by('order')
            self.fields['central_step'].queryset = steps
            self.fields['source_step'].queryset = steps
            self.fields['target_steps'].queryset = steps
            self.workflow = workflow
    
    def clean(self):
        cleaned_data = super().clean()
        transition_type = cleaned_data.get('transition_type')
        
        if transition_type == 'hub_spoke' and not cleaned_data.get('central_step'):
            raise ValidationError('Central step is required for hub and spoke pattern.')
        
        if transition_type == 'parallel':
            if not cleaned_data.get('source_step'):
                raise ValidationError('Source step is required for parallel branches.')
            if not cleaned_data.get('target_steps'):
                raise ValidationError('At least one target step is required for parallel branches.')
        
        if transition_type == 'custom':
            custom_transitions = cleaned_data.get('custom_transitions')
            if not custom_transitions:
                raise ValidationError('At least one custom transition must be selected.')
            
            try:
                import json
                transitions_data = json.loads(custom_transitions)
                if not transitions_data or len(transitions_data) == 0:
                    raise ValidationError('At least one custom transition must be selected.')
            except (json.JSONDecodeError, ValueError):
                raise ValidationError('Invalid custom transitions data.')
        
        return cleaned_data
    
    def create_transitions(self):
        """Create transitions based on the selected pattern"""
        transition_type = self.cleaned_data['transition_type']
        transitions_created = []
        
        if transition_type == 'sequential':
            # Create sequential transitions (Step 1 → Step 2 → Step 3...)
            steps = list(self.workflow.steps.order_by('order'))
            for i in range(len(steps) - 1):
                transition, created = WorkflowTransition.objects.get_or_create(
                    from_step=steps[i],
                    to_step=steps[i + 1],
                    defaults={'label': f'Next ({steps[i + 1].name})'}
                )
                if created:
                    transitions_created.append(transition)
        
        elif transition_type == 'hub_spoke':
            # Create hub and spoke pattern (All steps ↔ Central step)
            central_step = self.cleaned_data['central_step']
            other_steps = self.workflow.steps.exclude(id=central_step.id)
            
            for step in other_steps:
                # To central step
                transition1, created1 = WorkflowTransition.objects.get_or_create(
                    from_step=step,
                    to_step=central_step,
                    defaults={'label': f'To {central_step.name}'}
                )
                if created1:
                    transitions_created.append(transition1)
                
                # From central step
                transition2, created2 = WorkflowTransition.objects.get_or_create(
                    from_step=central_step,
                    to_step=step,
                    defaults={'label': f'To {step.name}'}
                )
                if created2:
                    transitions_created.append(transition2)
        
        elif transition_type == 'parallel':
            # Create parallel branches (One step → Multiple steps)
            source_step = self.cleaned_data['source_step']
            target_steps = self.cleaned_data['target_steps']
            
            for target_step in target_steps:
                transition, created = WorkflowTransition.objects.get_or_create(
                    from_step=source_step,
                    to_step=target_step,
                    defaults={'label': f'To {target_step.name}'}
                )
                if created:
                    transitions_created.append(transition)
        
        elif transition_type == 'custom':
            # Create custom selected transitions
            import json
            try:
                transitions_data = json.loads(self.cleaned_data['custom_transitions'])
                for transition_data in transitions_data:
                    from_step_id = transition_data.get('from_step')
                    to_step_id = transition_data.get('to_step')
                    
                    if from_step_id and to_step_id:
                        try:
                            from_step = WorkflowStep.objects.get(id=from_step_id, workflow=self.workflow)
                            to_step = WorkflowStep.objects.get(id=to_step_id, workflow=self.workflow)
                            
                            transition, created = WorkflowTransition.objects.get_or_create(
                                from_step=from_step,
                                to_step=to_step,
                                defaults={'label': f'{from_step.name} → {to_step.name}'}
                            )
                            if created:
                                transitions_created.append(transition)
                        except WorkflowStep.DoesNotExist:
                            continue  # Skip invalid step IDs
            except (json.JSONDecodeError, ValueError):
                pass  # Already handled in clean method
        
        return transitions_created


class TeamBookingForm(forms.ModelForm):
    """Form for creating team bookings"""
    
    class Meta:
        model = TeamBooking
        fields = [
            'title', 'description', 'job_type', 'start_time', 'end_time',
            'required_members'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Booking title'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Booking description...',
                'rows': 3
            }),
            'job_type': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500'
            }),
            'start_time': forms.DateTimeInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'type': 'datetime-local'
            }),
            'end_time': forms.DateTimeInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'type': 'datetime-local'
            }),
            'required_members': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'min': '1'
            }),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields['job_type'].queryset = JobType.objects.filter(
                organization=organization, is_active=True
            )

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')

        if start_time and end_time:
            if end_time <= start_time:
                raise ValidationError("End time must be after start time.")

        return cleaned_data


class SchedulingBookingForm(forms.ModelForm):
    """Form for creating bookings that integrate with the scheduling service"""
    
    # Allow choosing between CFlows team booking or Scheduling service booking
    booking_type = forms.ChoiceField(
        choices=[
            ('cflows', 'CFlows Team Booking'),
            ('scheduling', 'Scheduling Service Booking')
        ],
        initial='scheduling',
        widget=forms.RadioSelect(attrs={
            'class': 'text-purple-600 focus:ring-purple-500'
        }),
        help_text="Choose where to create the booking"
    )
    
    # Team selection for CFlows bookings
    team = forms.ModelChoiceField(
        queryset=None,
        empty_label="Select a team...",
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500'
        }),
        help_text="Team for CFlows booking (required for CFlows booking type)"
    )
    
    # Resource selection for Scheduling service bookings
    resource = forms.ModelChoiceField(
        queryset=None,
        empty_label="Select a resource...", 
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500'
        }),
        help_text="Resource for Scheduling service booking (required for scheduling booking type)"
    )
    
    # Duration field (easier than separate start/end times)
    duration_hours = forms.DecimalField(
        max_digits=5,
        decimal_places=2,
        initial=2.0,
        min_value=0.25,
        max_value=168.0,  # 1 week max
        widget=forms.NumberInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
            'step': '0.25',
            'min': '0.25',
            'max': '168'
        }),
        help_text="Duration in hours (e.g., 2.5 for 2 hours 30 minutes)"
    )
    
    class Meta:
        model = TeamBooking
        fields = [
            'title', 'description', 'job_type', 'start_time',
            'required_members'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Booking title'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Booking description...',
                'rows': 3
            }),
            'job_type': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500'
            }),
            'start_time': forms.DateTimeInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'type': 'datetime-local'
            }),
            'required_members': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'min': '1'
            }),
        }

    def __init__(self, *args, organization=None, work_item=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.organization = organization
        self.work_item = work_item
        
        if organization:
            # Set up team choices for CFlows bookings
            self.fields['team'].queryset = Team.objects.filter(
                organization=organization, is_active=True
            ).order_by('name')
            
            # Set up job type choices
            self.fields['job_type'].queryset = JobType.objects.filter(
                organization=organization, is_active=True
            ).order_by('name')
            
            # Set up resource choices for Scheduling service bookings
            from services.scheduling.models import SchedulableResource
            self.fields['resource'].queryset = SchedulableResource.objects.filter(
                organization=organization, is_active=True
            ).order_by('name')
        
        # Set default values if work_item is provided
        if work_item:
            if not self.fields['title'].initial:
                current_step_name = work_item.current_step.name if work_item.current_step else 'Processing'
                self.fields['title'].initial = f"{work_item.title} - {current_step_name}"
            
            if not self.fields['description'].initial:
                self.fields['description'].initial = f"Booking for work item: {work_item.title}"
            
            # Pre-select team if current step has assigned team
            if work_item.current_step and work_item.current_step.assigned_team:
                self.fields['team'].initial = work_item.current_step.assigned_team
                
            # Set estimated duration if available
            if work_item.current_step and work_item.current_step.estimated_duration_hours:
                self.fields['duration_hours'].initial = work_item.current_step.estimated_duration_hours

    def clean(self):
        cleaned_data = super().clean()
        booking_type = cleaned_data.get('booking_type')
        team = cleaned_data.get('team')
        resource = cleaned_data.get('resource')
        start_time = cleaned_data.get('start_time')
        duration_hours = cleaned_data.get('duration_hours')

        # Validate booking type requirements
        if booking_type == 'cflows' and not team:
            self.add_error('team', 'Team is required for CFlows bookings')
        elif booking_type == 'scheduling' and not resource:
            self.add_error('resource', 'Resource is required for Scheduling service bookings')

        # Calculate end time if both start time and duration are provided
        if start_time and duration_hours:
            from django.utils import timezone
            end_time = start_time + timezone.timedelta(hours=float(duration_hours))
            cleaned_data['end_time'] = end_time

            # Validate that end time is after start time
            if end_time <= start_time:
                self.add_error('duration_hours', 'Duration must be greater than 0')

        return cleaned_data
    
    def save_booking(self, user_profile):
        """Save the booking based on the selected type"""
        cleaned_data = self.cleaned_data
        booking_type = cleaned_data['booking_type']
        
        if booking_type == 'cflows':
            return self._save_cflows_booking(user_profile)
        else:
            return self._save_scheduling_booking(user_profile)
    
    def _save_cflows_booking(self, user_profile):
        """Save a CFlows TeamBooking"""
        from django.db import transaction
        
        with transaction.atomic():
            booking = TeamBooking.objects.create(
                team=self.cleaned_data['team'],
                work_item=self.work_item,
                workflow_step=self.work_item.current_step if self.work_item else None,
                job_type=self.cleaned_data.get('job_type'),
                title=self.cleaned_data['title'],
                description=self.cleaned_data.get('description', ''),
                start_time=self.cleaned_data['start_time'],
                end_time=self.cleaned_data['end_time'],
                required_members=self.cleaned_data.get('required_members', 1),
                booked_by=user_profile
            )
        
        return {
            'type': 'cflows',
            'booking': booking,
            'id': booking.id,
            'redirect_url': f'/services/cflows/work-items/{self.work_item.id}/' if self.work_item else '/services/cflows/bookings/'
        }
    
    def _save_scheduling_booking(self, user_profile):
        """Save a Scheduling service BookingRequest"""
        from services.scheduling.services import SchedulingService
        from django.db import transaction
    
        with transaction.atomic():
            # Use SchedulingService to create booking (includes auto-approval logic)
            scheduling_service = SchedulingService(self.organization)
        
            custom_data = {
                'work_item_id': self.work_item.id if self.work_item else None,
                'work_item_title': self.work_item.title if self.work_item else None,
                'workflow_name': self.work_item.workflow.name if self.work_item and self.work_item.workflow else None,
                'current_step': self.work_item.current_step.name if self.work_item and self.work_item.current_step else None,
                'job_type_id': self.cleaned_data['job_type'].id if self.cleaned_data.get('job_type') else None,
                'job_type_name': self.cleaned_data['job_type'].name if self.cleaned_data.get('job_type') else None,
            }
        
            booking = scheduling_service.create_booking(
                user_profile=user_profile,
                resource=self.cleaned_data['resource'],
                start_time=self.cleaned_data['start_time'],
                end_time=self.cleaned_data['end_time'],
                title=self.cleaned_data['title'],
                description=self.cleaned_data.get('description', ''),
                priority=self.work_item.priority if self.work_item else 'normal',
                source_service='cflows',
                source_object_type='WorkItem',
                source_object_id=str(self.work_item.id) if self.work_item else '',
                custom_data=custom_data
            )
    
        return {
            'type': 'scheduling',
            'booking': booking,
            'id': booking.id,
            'redirect_url': f'/services/cflows/work-items/{self.work_item.id}/' if self.work_item else '/services/scheduling/'
        }


class CustomFieldForm(forms.ModelForm):
    """Form for creating and editing custom fields"""
    
    # JSON field for options - displayed as textarea for easier editing
    options_text = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
            'rows': '3',
            'placeholder': 'Enter options, one per line (for select/multiselect fields)'
        }),
        required=False,
        help_text="Enter options one per line for select/multiselect fields"
    )
    
    class Meta:
        model = CustomField
        fields = [
            'name', 'label', 'field_type', 'is_required', 'default_value',
            'help_text', 'placeholder', 'min_length', 'max_length',
            'min_value', 'max_value', 'section', 'order', 'workflows',
            'workflow_steps', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'field_name (no spaces, lowercase)'
            }),
            'label': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Display label for users'
            }),
            'field_type': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500'
            }),
            'default_value': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Default value (optional)'
            }),
            'help_text': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Help text shown to users'
            }),
            'placeholder': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Placeholder text for input fields'
            }),
            'min_length': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'min': '0'
            }),
            'max_length': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'min': '1'
            }),
            'min_value': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'step': '0.01'
            }),
            'max_value': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'step': '0.01'
            }),
            'section': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Section name to group fields'
            }),
            'order': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'min': '0'
            }),
            'workflows': forms.SelectMultiple(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'size': '6'
            }),
            'workflow_steps': forms.SelectMultiple(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'size': '6'
            }),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Filter workflows and workflow steps to current organization
        if organization:
            self.fields['workflows'].queryset = Workflow.objects.filter(
                organization=organization, is_active=True
            ).order_by('name')
            self.fields['workflow_steps'].queryset = WorkflowStep.objects.filter(
                workflow__organization=organization
            ).select_related('workflow').order_by('workflow__name', 'order')
        
        # Populate options_text field if editing existing field
        if self.instance and self.instance.pk and self.instance.options:
            self.fields['options_text'].initial = '\n'.join(self.instance.options)
        
        # Add helpful labels for workflow steps
        workflow_step_choices = []
        for step in self.fields['workflow_steps'].queryset:
            workflow_step_choices.append((step.id, f"{step.workflow.name} → {step.name}"))
        self.fields['workflow_steps'].choices = workflow_step_choices

    def clean_name(self):
        """Ensure field name is valid for use as form field"""
        name = self.cleaned_data['name']
        if not name.replace('_', '').isalnum():
            raise ValidationError("Field name can only contain letters, numbers, and underscores")
        if name.startswith('_') or name.endswith('_'):
            raise ValidationError("Field name cannot start or end with underscore")
        return name.lower()

    def clean_options_text(self):
        """Convert options text to JSON array"""
        options_text = self.cleaned_data.get('options_text', '').strip()
        if not options_text:
            return []
        
        # Split by lines and clean up
        options = [line.strip() for line in options_text.split('\n') if line.strip()]
        return options

    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Set the options field from options_text
        instance.options = self.cleaned_data.get('options_text', [])
        
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class TeamForm(forms.ModelForm):
    """Form for creating and editing teams"""
    
    parent_team = forms.ModelChoiceField(
        queryset=Team.objects.none(),
        required=False,
        empty_label="--- Top-level team (no parent) ---",
        widget=forms.Select(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500'
        }),
        help_text="Select a parent team to create a sub-team, or leave empty for a top-level team"
    )
    
    class Meta:
        model = Team
        fields = [
            'name', 'description', 'parent_team', 'default_capacity', 'color', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
                'placeholder': 'Enter team name'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
                'placeholder': 'Describe this team\'s purpose and responsibilities...',
                'rows': 3
            }),
            'default_capacity': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
                'min': '1',
                'max': '50'
            }),
            'color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'w-16 h-10 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'rounded text-indigo-600 focus:ring-indigo-500'
            }),
        }
        help_texts = {
            'default_capacity': 'Default number of team members available for scheduling',
            'color': 'Team color for visual identification in calendars and reports',
        }

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        current_team = kwargs.pop('current_team', None)
        super().__init__(*args, **kwargs)
        
        if organization:
            # Get teams that can be parent teams (exclude current team and its descendants to prevent circular references)
            potential_parents = Team.objects.filter(organization=organization, is_active=True)
            
            if current_team:
                # Exclude current team and its descendants to prevent circular references
                excluded_teams = [current_team.id]
                excluded_teams.extend([team.id for team in current_team.get_all_sub_teams(include_self=False)])
                potential_parents = potential_parents.exclude(id__in=excluded_teams)
            
            # Order by hierarchy for better display
            potential_parents = potential_parents.order_by('name')
            
            # Create choices with hierarchy indication
            choices = [(team.id, team.full_hierarchy_name) for team in potential_parents]
            self.fields['parent_team'].choices = [('', '--- Top-level team (no parent) ---')] + choices
        
        # Set initial value if editing
        if self.instance and self.instance.pk and self.instance.parent_team:
            self.fields['parent_team'].initial = self.instance.parent_team.id

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        
        # Set initial values
        if not self.instance.pk:
            self.fields['default_capacity'].initial = 3
            self.fields['is_active'].initial = True

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if not name:
            raise ValidationError('Team name is required.')
        
        # Check for duplicate names within the organization
        if self.organization:
            existing = Team.objects.filter(
                organization=self.organization,
                name__iexact=name
            )
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            
            if existing.exists():
                raise ValidationError('A team with this name already exists in your organization.')
        
        return name

    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Set organization if provided
        if self.organization:
            instance.organization = self.organization
        
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class WorkflowCreationForm(forms.ModelForm):
    """Enhanced workflow creation form with step creation"""
    
    # Step creation fields
    step_names = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
            'rows': 4,
            'placeholder': 'Enter step names, one per line:\nStep 1: Initial Review\nStep 2: Processing\nStep 3: Final Approval'
        }),
        help_text='Enter workflow step names, one per line. Each step will be created in order.',
        required=False
    )
    
    class Meta:
        model = Workflow
        fields = ['name', 'description', 'auto_assign', 'requires_approval']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
                'placeholder': 'Enter workflow name'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500',
                'placeholder': 'Describe this workflow\'s purpose and process...',
                'rows': 3
            }),
            'auto_assign': forms.CheckboxInput(attrs={
                'class': 'rounded text-indigo-600 focus:ring-indigo-500'
            }),
            'requires_approval': forms.CheckboxInput(attrs={
                'class': 'rounded text-indigo-600 focus:ring-indigo-500'
            }),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization

    def clean_step_names(self):
        step_names = self.cleaned_data.get('step_names', '').strip()
        if not step_names:
            return []
        
        # Parse step names
        steps = []
        for line in step_names.split('\n'):
            line = line.strip()
            if line:
                # Remove step numbers if present (e.g., "Step 1: Review" -> "Review")
                if ':' in line:
                    parts = line.split(':', 1)
                    if len(parts) > 1:
                        line = parts[1].strip()
                steps.append(line)
        
        if len(steps) > 20:
            raise ValidationError('Maximum 20 steps allowed per workflow.')
        
        return steps

    def save(self, commit=True, created_by=None):
        instance = super().save(commit=False)
        
        # Set organization and creator
        if self.organization:
            instance.organization = self.organization
        if created_by:
            instance.created_by = created_by
        
        if commit:
            instance.save()
            
            # Create workflow steps
            step_names = self.cleaned_data.get('step_names', [])
            for i, step_name in enumerate(step_names, 1):
                WorkflowStep.objects.create(
                    workflow=instance,
                    name=step_name,
                    order=i,
                    is_terminal=(i == len(step_names))  # Mark last step as terminal
                )
            
            # Create basic transitions between sequential steps
            steps = list(instance.steps.order_by('order'))
            for i in range(len(steps) - 1):
                WorkflowTransition.objects.create(
                    from_step=steps[i],
                    to_step=steps[i + 1],
                    label=f'Proceed to {steps[i + 1].name}'
                )
            
            self.save_m2m()
        
        return instance


class WorkItemFilterViewForm(forms.ModelForm):
    """Form for creating and editing saved work item filter views"""
    
    class Meta:
        model = WorkItemFilterView
        fields = ['name', 'is_default']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
                'placeholder': 'Enter filter view name'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
    
    def clean_name(self):
        name = self.cleaned_data['name']
        if self.user:
            # Check for duplicate names for this user (excluding current instance)
            existing = WorkItemFilterView.objects.filter(
                user=self.user, 
                name__iexact=name
            )
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            
            if existing.exists():
                raise ValidationError('A filter view with this name already exists.')
        
        return name
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
        
        if commit:
            instance.save()
        
        return instance


class SaveFilterViewForm(forms.Form):
    """Form for saving current filter state as a new filter view"""
    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500',
            'placeholder': 'Enter filter view name'
        })
    )
    is_default = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 text-purple-600 focus:ring-purple-500 border-gray-300 rounded'
        })
    )
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.filter_data = kwargs.pop('filter_data', {})
        super().__init__(*args, **kwargs)
    
    def clean_name(self):
        name = self.cleaned_data['name']
        if self.user:
            if WorkItemFilterView.objects.filter(user=self.user, name__iexact=name).exists():
                raise ValidationError('A filter view with this name already exists.')
        return name
    
    def save(self):
        if not self.user:
            return None
        
        filter_view = WorkItemFilterView.objects.create(
            name=self.cleaned_data['name'],
            user=self.user,
            is_default=self.cleaned_data['is_default'],
            workflow=self.filter_data.get('workflow', ''),
            assignee=self.filter_data.get('assignee', ''),
            priority=self.filter_data.get('priority', ''),
            status=self.filter_data.get('status', ''),
            search=self.filter_data.get('search', ''),
            sort=self.filter_data.get('sort', '-updated_at'),
        )
        
        return filter_view
