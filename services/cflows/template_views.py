from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
import json
from datetime import datetime

from .models import (
    Workflow, WorkflowStep, WorkflowTransition, WorkflowTemplate
)


@login_required
def template_list(request):
    """List all available workflow templates"""
    templates = WorkflowTemplate.objects.filter(is_public=True).order_by('category', 'name')
    
    # Group by category
    templates_by_category = {}
    for template in templates:
        if template.category not in templates_by_category:
            templates_by_category[template.category] = []
        templates_by_category[template.category].append(template)
    
    return render(request, 'cflows/template_list.html', {
        'templates_by_category': templates_by_category,
        'page_title': 'Workflow Templates'
    })


@login_required
def template_detail(request, template_id):
    """Show template details and preview"""
    template = get_object_or_404(WorkflowTemplate, id=template_id, is_public=True)
    
    # Parse template data
    template_steps = []
    template_transitions = []
    
    if template.template_data:
        template_steps = template.template_data.get('steps', [])
        template_transitions = template.template_data.get('transitions', [])
    
    return render(request, 'cflows/template_detail.html', {
        'template': template,
        'template_steps': template_steps,
        'template_transitions': template_transitions,
        'page_title': f'Template: {template.name}'
    })


@login_required
def create_from_template(request, template_id):
    """Create a new workflow from a template"""
    template = get_object_or_404(WorkflowTemplate, id=template_id, is_public=True)
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        
        if not name:
            messages.error(request, 'Workflow name is required.')
            return render(request, 'cflows/create_from_template.html', {
                'template': template
            })
        
        try:
            with transaction.atomic():
                # Create the workflow
                workflow = Workflow.objects.create(
                    name=name,
                    description=description,
                    organization=request.user.userprofile.organization,
                    created_by=request.user,
                    modified_by=request.user
                )
                
                # Create steps from template
                step_mapping = {}
                if template.template_data and 'steps' in template.template_data:
                    for step_data in template.template_data['steps']:
                        step = WorkflowStep.objects.create(
                            workflow=workflow,
                            name=step_data['name'],
                            description=step_data.get('description', ''),
                            step_order=step_data.get('order', 1),
                            requires_booking=step_data.get('requires_booking', False),
                            estimated_duration_hours=step_data.get('estimated_duration_hours', 0),
                            is_terminal=step_data.get('is_terminal', False)
                        )
                        step_mapping[step_data['id']] = step
                
                # Create transitions from template
                if template.template_data and 'transitions' in template.template_data:
                    for transition_data in template.template_data['transitions']:
                        from_step_id = transition_data.get('from_step_id')
                        to_step_id = transition_data.get('to_step_id')
                        
                        if from_step_id in step_mapping and to_step_id in step_mapping:
                            WorkflowTransition.objects.create(
                                from_step=step_mapping[from_step_id],
                                to_step=step_mapping[to_step_id],
                                label=transition_data.get('label', f'Go to {step_mapping[to_step_id].name}'),
                                requires_confirmation=transition_data.get('requires_confirmation', False)
                            )
            
            messages.success(request, f'Workflow "{name}" created successfully from template!')
            return redirect('cflows:workflow_detail', workflow_id=workflow.id)
            
        except Exception as e:
            messages.error(request, f'Error creating workflow: {str(e)}')
    
    return render(request, 'cflows/create_from_template.html', {
        'template': template,
        'page_title': f'Create Workflow from Template: {template.name}'
    })


@login_required
@require_POST
def save_as_template(request, workflow_id):
    """Save an existing workflow as a template"""
    workflow = get_object_or_404(
        Workflow, 
        id=workflow_id, 
        organization=request.user.userprofile.organization
    )
    
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        category = data.get('category', 'Other').strip()
        is_public = data.get('is_public', False)
        
        if not name:
            return JsonResponse({'success': False, 'error': 'Template name is required'})
        
        # Build template data from workflow
        steps = []
        transitions = []
        
        # Get steps
        workflow_steps = workflow.steps.all().order_by('step_order')
        step_mapping = {}
        
        for i, step in enumerate(workflow_steps):
            step_id = f'step_{i+1}'
            step_mapping[step.id] = step_id
            
            steps.append({
                'id': step_id,
                'name': step.name,
                'description': step.description,
                'order': step.step_order,
                'requires_booking': step.requires_booking,
                'estimated_duration_hours': float(step.estimated_duration_hours or 0),
                'is_terminal': step.is_terminal
            })
        
        # Get transitions
        for transition in WorkflowTransition.objects.filter(from_step__workflow=workflow):
            if transition.from_step.id in step_mapping and transition.to_step.id in step_mapping:
                transitions.append({
                    'from_step_id': step_mapping[transition.from_step.id],
                    'to_step_id': step_mapping[transition.to_step.id],
                    'label': transition.label,
                    'requires_confirmation': transition.requires_confirmation
                })
        
        template_data = {
            'steps': steps,
            'transitions': transitions,
            'source_workflow_id': workflow.id,
            'created_from': workflow.name,
            'created_at': datetime.now().isoformat()
        }
        
        # Create template
        template = WorkflowTemplate.objects.create(
            name=name,
            description=description,
            category=category,
            is_public=is_public,
            template_data=template_data,
            created_by=request.user,
            organization=request.user.userprofile.organization if not is_public else None
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Template "{name}" created successfully!',
            'template_id': template.id
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def template_preview(request, template_id):
    """Preview template as JSON for API access"""
    template = get_object_or_404(WorkflowTemplate, id=template_id, is_public=True)
    
    # Check access permissions
    if not template.is_public and template.organization != request.user.userprofile.organization:
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    return JsonResponse({
        'template': {
            'id': template.id,
            'name': template.name,
            'description': template.description,
            'category': template.category,
            'is_public': template.is_public,
            'template_data': template.template_data,
            'created_by': template.created_by.get_full_name() if template.created_by else None,
            'created_at': template.created_at.isoformat(),
            'modified_at': template.modified_at.isoformat()
        }
    })
