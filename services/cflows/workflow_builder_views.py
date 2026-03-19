from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.db import transaction, models
from django.urls import reverse
from core.views import require_organization_access
from core.models import Team, UserProfile
from .models import (
    Workflow, WorkflowStep, WorkflowTransition, WorkflowTemplate, CustomField
)
from .forms import WorkflowForm
import json


def get_user_profile(request):
    """Get user profile for the current user"""
    if not request.user.is_authenticated:
        return None
    try:
        return request.user.mediap_profile
    except UserProfile.DoesNotExist:
        return None


@login_required
@require_organization_access
def workflow_builder(request):
    """Enhanced workflow builder with templates and custom creation"""
    profile = get_user_profile(request)
    
    if not profile:
        return render(request, 'cflows/no_profile.html')
    
    # Get available templates
    templates = WorkflowTemplate.objects.filter(
        models.Q(is_public=True) | models.Q(created_by_org=profile.organization)
    ).order_by('category', 'name')
    
    # Group templates by category
    template_categories = {}
    for template in templates:
        if template.category not in template_categories:
            template_categories[template.category] = []
        template_categories[template.category].append(template)
    
    # Get available teams
    teams = Team.objects.filter(
        organization=profile.organization,
        is_active=True
    ).order_by('name')
    
    context = {
        'profile': profile,
        'templates': templates,
        'template_categories': template_categories,
        'teams': teams,
        'page_title': 'Workflow Builder'
    }
    
    return render(request, 'cflows/workflow_builder.html', context)


@login_required
@require_organization_access
@require_POST
def create_workflow_from_template(request, template_id):
    """Create a workflow from a template with optional customization"""
    profile = get_user_profile(request)
    
    if not profile:
        return JsonResponse({'error': 'No user profile found'}, status=400)
    
    template = get_object_or_404(WorkflowTemplate, id=template_id)
    
    # Get workflow details from request
    workflow_name = request.POST.get('workflow_name')
    workflow_description = request.POST.get('workflow_description', template.description)
    owner_team_id = request.POST.get('owner_team')
    
    if not workflow_name:
        return JsonResponse({'error': 'Workflow name is required'}, status=400)
    
    if not owner_team_id:
        return JsonResponse({'error': 'Owner team is required'}, status=400)
    
    try:
        owner_team = Team.objects.get(
            id=owner_team_id,
            organization=profile.organization
        )
    except Team.DoesNotExist:
        return JsonResponse({'error': 'Invalid owner team'}, status=400)
    
    # Check if workflow name already exists
    if Workflow.objects.filter(
        organization=profile.organization,
        name=workflow_name
    ).exists():
        return JsonResponse({'error': 'A workflow with this name already exists'}, status=400)
    
    try:
        with transaction.atomic():
            # Create workflow
            workflow = Workflow.objects.create(
                organization=profile.organization,
                name=workflow_name,
                description=workflow_description,
                template=template,
                owner_team=owner_team,
                created_by=profile
            )
            
            # Apply template structure
            apply_workflow_template(workflow)
            
            # Update template usage count
            template.usage_count += 1
            template.save()
            
            return JsonResponse({
                'success': True,
                'workflow_id': workflow.id,
                'redirect_url': reverse('cflows:workflow_detail', args=[workflow.id])
            })
            
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_organization_access
@require_POST
def create_custom_workflow(request):
    """Create a completely custom workflow"""
    profile = get_user_profile(request)
    
    if not profile:
        return JsonResponse({'error': 'No user profile found'}, status=400)
    
    # Get workflow details
    workflow_name = request.POST.get('workflow_name')
    workflow_description = request.POST.get('workflow_description', '')
    owner_team_id = request.POST.get('owner_team')
    steps_data = request.POST.get('steps_data')
    
    if not workflow_name:
        return JsonResponse({'error': 'Workflow name is required'}, status=400)
    
    if not owner_team_id:
        return JsonResponse({'error': 'Owner team is required'}, status=400)
    
    if not steps_data:
        return JsonResponse({'error': 'At least one workflow step is required'}, status=400)
    
    try:
        owner_team = Team.objects.get(
            id=owner_team_id,
            organization=profile.organization
        )
    except Team.DoesNotExist:
        return JsonResponse({'error': 'Invalid owner team'}, status=400)
    
    # Check if workflow name already exists
    if Workflow.objects.filter(
        organization=profile.organization,
        name=workflow_name
    ).exists():
        return JsonResponse({'error': 'A workflow with this name already exists'}, status=400)
    
    try:
        # Parse steps data
        steps = json.loads(steps_data)
        if not steps or len(steps) == 0:
            return JsonResponse({'error': 'At least one workflow step is required'}, status=400)
        
        with transaction.atomic():
            # Create workflow
            workflow = Workflow.objects.create(
                organization=profile.organization,
                name=workflow_name,
                description=workflow_description,
                owner_team=owner_team,
                created_by=profile
            )
            
            # Create steps
            step_objects = []
            for i, step_data in enumerate(steps):
                step_name = step_data.get('name', '').strip()
                if not step_name:
                    continue
                    
                step = WorkflowStep.objects.create(
                    workflow=workflow,
                    name=step_name,
                    description=step_data.get('description', ''),
                    order=i + 1,
                    requires_booking=step_data.get('requires_booking', False),
                    estimated_duration_hours=step_data.get('estimated_duration_hours'),
                    is_terminal=(i == len(steps) - 1)
                )
                
                # Assign team if specified
                team_id = step_data.get('assigned_team_id')
                if team_id:
                    try:
                        team = Team.objects.get(
                            id=team_id,
                            organization=profile.organization
                        )
                        step.assigned_team = team
                        step.save()
                    except Team.DoesNotExist:
                        pass
                
                # Create custom fields for this step
                custom_fields_data = step_data.get('custom_fields', [])
                for field_data in custom_fields_data:
                    field_name = field_data.get('name', '').strip()
                    field_label = field_data.get('label', '').strip()
                    
                    if field_name and field_label:
                        from .models import CustomField
                        
                        # Check if field name already exists for this organization
                        field_name_lower = field_name.lower().replace(' ', '_')
                        existing_field = CustomField.objects.filter(
                            organization=profile.organization,
                            name=field_name_lower
                        ).first()
                        
                        if existing_field:
                            # Use existing field and associate with this step
                            existing_field.workflow_steps.add(step)
                        else:
                            # Create new custom field
                            custom_field = CustomField.objects.create(
                                organization=profile.organization,
                                name=field_name_lower,
                                label=field_label,
                                field_type=field_data.get('field_type', 'text'),
                                is_required=field_data.get('is_required', False),
                                help_text=field_data.get('help_text', ''),
                                options=field_data.get('options', [])
                            )
                            # Associate with this workflow and step
                            custom_field.workflows.add(workflow)
                            custom_field.workflow_steps.add(step)
                
                step_objects.append(step)
            
            # Create basic sequential transitions
            for i in range(len(step_objects) - 1):
                WorkflowTransition.objects.create(
                    from_step=step_objects[i],
                    to_step=step_objects[i + 1],
                    label=f'Proceed to {step_objects[i + 1].name}'
                )
            
            return JsonResponse({
                'success': True,
                'workflow_id': workflow.id,
                'redirect_url': reverse('cflows:workflow_detail', args=[workflow.id])
            })
            
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid steps data format'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_organization_access
def get_template_preview(request, template_id):
    """Get template preview data for customization"""
    profile = get_user_profile(request)
    
    if not profile:
        return JsonResponse({'error': 'No user profile found'}, status=400)
    
    template = get_object_or_404(WorkflowTemplate, id=template_id)
    
    # Return template data for preview/customization
    return JsonResponse({
        'success': True,
        'template': {
            'id': template.id,
            'name': template.name,
            'description': template.description,
            'category': template.category,
            'steps': template.template_data.get('steps', []),
            'transitions': template.template_data.get('transitions', [])
        }
    })


def apply_workflow_template(workflow):
    """Apply template structure to a workflow (improved version)"""
    if not workflow.template or not workflow.template.template_data:
        return
    
    template_data = workflow.template.template_data
    steps_data = template_data.get('steps', [])
    transitions_data = template_data.get('transitions', [])
    
    # Create steps
    step_mapping = {}
    for step_data in steps_data:
        step = WorkflowStep.objects.create(
            workflow=workflow,
            name=step_data['name'],
            description=step_data.get('description', ''),
            order=step_data.get('order', 1),
            requires_booking=step_data.get('requires_booking', False),
            estimated_duration_hours=step_data.get('estimated_duration_hours'),
            is_terminal=step_data.get('is_terminal', False),
            data_schema=step_data.get('data_schema', {})
        )
        step_mapping[step_data['id']] = step
    
    # Create transitions
    for transition_data in transitions_data:
        from_step = step_mapping.get(transition_data['from_step_id'])
        to_step = step_mapping.get(transition_data['to_step_id'])
        
        if from_step and to_step:
            WorkflowTransition.objects.create(
                from_step=from_step,
                to_step=to_step,
                label=transition_data.get('label', ''),
                condition=transition_data.get('condition', {})
            )


@login_required
@require_organization_access
@require_POST
def customize_template_workflow(request, template_id):
    """Create workflow from template with custom modifications"""
    profile = get_user_profile(request)
    
    if not profile:
        return JsonResponse({'error': 'No user profile found'}, status=400)
    
    template = get_object_or_404(WorkflowTemplate, id=template_id)
    
    # Get workflow details
    workflow_name = request.POST.get('workflow_name')
    workflow_description = request.POST.get('workflow_description', '')
    owner_team_id = request.POST.get('owner_team')
    custom_steps_data = request.POST.get('custom_steps_data')
    
    if not workflow_name:
        return JsonResponse({'error': 'Workflow name is required'}, status=400)
    
    if not owner_team_id:
        return JsonResponse({'error': 'Owner team is required'}, status=400)
    
    try:
        owner_team = Team.objects.get(
            id=owner_team_id,
            organization=profile.organization
        )
    except Team.DoesNotExist:
        return JsonResponse({'error': 'Invalid owner team'}, status=400)
    
    # Check if workflow name already exists
    if Workflow.objects.filter(
        organization=profile.organization,
        name=workflow_name
    ).exists():
        return JsonResponse({'error': 'A workflow with this name already exists'}, status=400)
    
    try:
        # Parse custom steps if provided
        custom_steps = []
        if custom_steps_data:
            custom_steps = json.loads(custom_steps_data)
        
        with transaction.atomic():
            # Create workflow
            workflow = Workflow.objects.create(
                organization=profile.organization,
                name=workflow_name,
                description=workflow_description,
                template=template,
                owner_team=owner_team,
                created_by=profile
            )
            
            # Use custom steps if provided, otherwise use template
            if custom_steps:
                # Create custom steps
                step_objects = []
                for i, step_data in enumerate(custom_steps):
                    step = WorkflowStep.objects.create(
                        workflow=workflow,
                        name=step_data['name'],
                        description=step_data.get('description', ''),
                        order=i + 1,
                        requires_booking=step_data.get('requires_booking', False),
                        estimated_duration_hours=step_data.get('estimated_duration_hours'),
                        is_terminal=step_data.get('is_terminal', i == len(custom_steps) - 1)
                    )
                    
                    # Assign team if specified
                    team_id = step_data.get('assigned_team_id')
                    if team_id:
                        try:
                            team = Team.objects.get(
                                id=team_id,
                                organization=profile.organization
                            )
                            step.assigned_team = team
                            step.save()
                        except Team.DoesNotExist:
                            pass
                    
                    # Create custom fields for this step
                    custom_fields_data = step_data.get('custom_fields', [])
                    for field_data in custom_fields_data:
                        field_name = field_data.get('name', '').strip()
                        field_label = field_data.get('label', '').strip()
                        
                        if field_name and field_label:
                            # Check if field name already exists for this organization
                            field_name_lower = field_name.lower().replace(' ', '_')
                            existing_field = CustomField.objects.filter(
                                organization=profile.organization,
                                name=field_name_lower
                            ).first()
                            
                            if existing_field:
                                # Use existing field and associate with this step
                                existing_field.workflow_steps.add(step)
                            else:
                                # Create new custom field
                                custom_field = CustomField.objects.create(
                                    organization=profile.organization,
                                    name=field_name_lower,
                                    label=field_label,
                                    field_type=field_data.get('field_type', 'text'),
                                    is_required=field_data.get('is_required', False),
                                    help_text=field_data.get('help_text', ''),
                                    options=field_data.get('options', [])
                                )
                                # Associate with this workflow and step
                                custom_field.workflows.add(workflow)
                                custom_field.workflow_steps.add(step)
                    
                    step_objects.append(step)
                
                # Create sequential transitions
                for i in range(len(step_objects) - 1):
                    WorkflowTransition.objects.create(
                        from_step=step_objects[i],
                        to_step=step_objects[i + 1],
                        label=f'Proceed to {step_objects[i + 1].name}'
                    )
            else:
                # Apply original template
                apply_workflow_template(workflow)
            
            # Update template usage count
            template.usage_count += 1
            template.save()
            
            return JsonResponse({
                'success': True,
                'workflow_id': workflow.id,
                'redirect_url': reverse('cflows:workflow_detail', args=[workflow.id])
            })
            
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)