from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, Count, Prefetch, Case, When, IntegerField
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from django.db import transaction, models
from core.models import Organization, UserProfile, Team, JobType, CalendarEvent
from core.views import require_organization_access, require_business_organization
from core.decorators import require_permission
from .models import (
    Workflow, WorkflowStep, WorkflowTransition, WorkflowTemplate,
    WorkItem, WorkItemHistory, WorkItemComment, WorkItemAttachment,
    WorkItemRevision, TeamBooking, CustomField, WorkItemCustomFieldValue,
    WorkItemFilterView
)
from .forms import (
    WorkflowForm, WorkflowStepForm, WorkItemForm, WorkItemCommentForm,
    WorkItemAttachmentForm, WorkflowTransitionForm, TeamBookingForm,
    CustomFieldForm, TeamForm, WorkflowCreationForm, BulkTransitionForm,
    WorkflowFieldConfigForm, SchedulingBookingForm, WorkItemFilterViewForm,
    SaveFilterViewForm
)
import json
from django.views.decorators.http import require_GET


def apply_workflow_template(workflow):
    """Apply template structure to a workflow"""
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


def get_user_profile(request):
    """Get or create user profile for the current user"""
    if not request.user.is_authenticated:
        return None
    
    try:
        return request.user.mediap_profile
    except UserProfile.DoesNotExist:
        # For now, return None if no profile exists
        # In a real app, you might redirect to a profile setup page
        return None


@login_required
@require_organization_access
def index(request):
    """CFlows homepage - Dashboard"""
    profile = request.user.mediap_profile
    
    if not profile:
        return render(request, 'cflows/no_profile.html')
    
    organization = profile.organization
    
    # Get dashboard statistics
    stats = {
        'total_workflows': organization.workflows.filter(is_active=True).count(),
        'active_work_items': WorkItem.objects.filter(
            workflow__organization=organization,
            is_completed=False
        ).count(),
        'my_assigned_items': WorkItem.objects.filter(
            workflow__organization=organization,
            current_assignee=profile,
            is_completed=False
        ).count(),
        'my_teams_count': profile.teams.filter(is_active=True).count(),
    }
    
    # Recent work items
    recent_work_items = WorkItem.objects.filter(
        workflow__organization=organization
    ).select_related(
        'workflow', 'current_step', 'current_assignee__user', 'created_by__user'
    ).order_by('-updated_at')[:10]
    
    # Upcoming bookings for user's teams
    user_teams = profile.teams.filter(is_active=True)
    upcoming_bookings = TeamBooking.objects.filter(
        team__in=user_teams,
        start_time__gte=timezone.now(),
        is_completed=False
    ).select_related(
        'team', 'work_item', 'job_type', 'booked_by__user'
    ).order_by('start_time')[:5]
    
    context = {
        'profile': profile,
        'organization': organization,
        'stats': stats,
        'recent_work_items': recent_work_items,
        'upcoming_bookings': upcoming_bookings,
    }
    
    return render(request, 'cflows/dashboard.html', context)


@login_required
def workflows_list(request):
    """List workflows for the user's organization"""
    profile = get_user_profile(request)
    
    if not profile:
        return render(request, 'cflows/no_profile.html')
    
    workflows = Workflow.objects.filter(
        organization=profile.organization,
        is_active=True
    ).select_related('created_by__user').annotate(
        step_count=Count('steps'),
        work_item_count=Count('work_items')
    ).order_by('name')
    
    # Pagination
    paginator = Paginator(workflows, 12)  # Show 12 workflows per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'profile': profile,
        'page_obj': page_obj,
        'workflows': page_obj,
    }
    
    return render(request, 'cflows/workflows_list.html', context)


@login_required
@require_organization_access
@login_required
@require_organization_access
@require_permission('workflow.create')
def create_workflow(request):
    """Create new workflow with enhanced form"""
    profile = get_user_profile(request)
    
    if not profile:
        return render(request, 'cflows/no_profile.html')
    
    if request.method == 'POST':
        form = WorkflowForm(request.POST, organization=profile.organization, user_profile=profile)
        if form.is_valid():
            workflow = form.save(commit=False)
            workflow.organization = profile.organization
            workflow.created_by = profile
            workflow.save()
            
            # Save many-to-many fields
            form.save_m2m()
            
            # If created from template, apply template structure
            if workflow.template:
                apply_workflow_template(workflow)
            
            # Handle custom fields if provided
            custom_fields_json = request.POST.get('custom_fields_json')
            if custom_fields_json:
                try:
                    import json
                    custom_fields_data = json.loads(custom_fields_json)
                    
                    # Create custom fields for this workflow
                    for field_data in custom_fields_data:
                        field_name = field_data.get('name', '').strip().lower()
                        field_label = field_data.get('label', '').strip()
                        
                        if field_name and field_label:
                            # Check if field already exists
                            existing_field = CustomField.objects.filter(
                                organization=profile.organization,
                                name=field_name
                            ).first()
                            
                            if existing_field:
                                # Associate existing field with this workflow
                                existing_field.workflows.add(workflow)
                            else:
                                # Create new custom field
                                custom_field = CustomField.objects.create(
                                    organization=profile.organization,
                                    name=field_name,
                                    label=field_label,
                                    field_type=field_data.get('field_type', 'text'),
                                    is_required=field_data.get('is_required', False),
                                    help_text=field_data.get('help_text', ''),
                                    options=field_data.get('options', []),
                                    is_active=True
                                )
                                # Associate with this workflow
                                custom_field.workflows.add(workflow)
                except (json.JSONDecodeError, ValueError):
                    messages.warning(request, 'Could not parse custom fields data.')
            
            messages.success(request, f'Workflow "{workflow.name}" created successfully!')
            return redirect('cflows:workflow_detail', workflow_id=workflow.id)
    else:
        form = WorkflowForm(organization=profile.organization, user_profile=profile)
    
    # Get available templates
    templates = WorkflowTemplate.objects.filter(
        Q(is_public=True) | Q(created_by_org=profile.organization)
    ).order_by('category', 'name')
    
    context = {
        'profile': profile,
        'form': form,
        'templates': templates,
    }
    
    return render(request, 'cflows/create_workflow.html', context)


@login_required
@require_organization_access
@login_required
@require_organization_access
@require_permission('workflow.view')
def workflow_detail(request, workflow_id):
    """Detailed view of a workflow with steps and statistics"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'cflows/no_profile.html')
    
    workflow = get_object_or_404(
        Workflow.objects.select_related('created_by__user', 'template'),
        id=workflow_id,
        organization=profile.organization
    )
    
    # Get workflow steps with transitions
    steps = workflow.steps.prefetch_related(
        'outgoing_transitions__to_step',
        'incoming_transitions__from_step'
    ).order_by('order')
    
    # Statistics
    stats = {
        'total_items': workflow.work_items.count(),
        'active_items': workflow.work_items.filter(is_completed=False).count(),
        'completed_items': workflow.work_items.filter(is_completed=True).count(),
        'steps_count': steps.count(),
    }
    
    # Recent work items
    recent_items = workflow.work_items.select_related(
        'current_step', 'current_assignee__user', 'created_by__user'
    ).order_by('-updated_at')[:10]
    
    context = {
        'profile': profile,
        'workflow': workflow,
        'steps': steps,
        'stats': stats,
        'recent_items': recent_items,
    }
    
    return render(request, 'cflows/workflow_detail.html', context)


@login_required
@require_organization_access
@require_permission('workflow.configure')
def workflow_field_config(request, workflow_id):
    """Configure which fields are shown/hidden/replaced for work items in this workflow"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    workflow = get_object_or_404(
        Workflow,
        id=workflow_id,
        organization=profile.organization
    )
    
    # Check permissions
    if not (profile.is_organization_admin or profile.has_staff_panel_access):
        messages.error(request, "You don't have permission to configure workflow fields.")
        return redirect('cflows:workflow_detail', workflow_id=workflow_id)
    
    if request.method == 'POST':
        form = WorkflowFieldConfigForm(
            request.POST,
            workflow=workflow,
            organization=profile.organization
        )
        if form.is_valid():
            config = form.save_config()
            messages.success(request, f"Field configuration saved successfully for {workflow.name}")
            
            # Handle custom fields if provided
            custom_fields_json = request.POST.get('custom_fields_json')
            if custom_fields_json:
                try:
                    import json
                    custom_fields_data = json.loads(custom_fields_json)
                    
                    # Create custom fields for this workflow
                    for field_data in custom_fields_data:
                        field_name = field_data.get('name', '').strip().lower()
                        field_label = field_data.get('label', '').strip()
                        
                        if field_name and field_label:
                            # Check if field already exists
                            existing_field = CustomField.objects.filter(
                                organization=profile.organization,
                                name=field_name
                            ).first()
                            
                            if existing_field:
                                # Associate existing field with this workflow
                                existing_field.workflows.add(workflow)
                            else:
                                # Create new custom field
                                custom_field = CustomField.objects.create(
                                    organization=profile.organization,
                                    name=field_name,
                                    label=field_label,
                                    field_type=field_data.get('field_type', 'text'),
                                    is_required=field_data.get('is_required', False),
                                    help_text=field_data.get('help_text', ''),
                                    options=field_data.get('options', []),
                                    is_active=True
                                )
                                # Associate with this workflow
                                custom_field.workflows.add(workflow)
                except (json.JSONDecodeError, ValueError):
                    messages.warning(request, 'Could not parse custom fields data.')
            
            # Handle custom field removals
            remove_field_ids = request.POST.getlist('remove_custom_field_ids')
            if remove_field_ids:
                for field_id in remove_field_ids:
                    try:
                        custom_field = CustomField.objects.get(id=int(field_id))
                        custom_field.workflows.remove(workflow)
                    except (CustomField.DoesNotExist, ValueError):
                        pass
            
            return redirect('cflows:workflow_detail', workflow_id=workflow_id)
    else:
        form = WorkflowFieldConfigForm(
            workflow=workflow,
            organization=profile.organization
        )
    
    # Get current configuration for display
    current_config = workflow.get_active_fields()
    
    # Get custom fields for this workflow
    custom_fields = CustomField.objects.filter(
        organization=profile.organization,
        workflows=workflow,
        is_active=True
    ).order_by('section', 'order', 'label')
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'workflow': workflow,
        'form': form,
        'current_config': current_config,
        'custom_fields': custom_fields,
        'title': f'Configure Fields - {workflow.name}'
    }
    
    return render(request, 'cflows/workflow_field_config.html', context)


@login_required
@require_organization_access
def work_items_list(request):
    """Enhanced work items list with filtering and search"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'cflows/no_profile.html')
    
    # Check if this is an API request
    is_api = request.GET.get('api') == 'true'
    
    # Base queryset
    work_items = WorkItem.objects.filter(
        workflow__organization=profile.organization
    ).select_related(
        'workflow', 'current_step', 'current_assignee__user', 'created_by__user'
    ).prefetch_related('attachments', 'comments')
    
    # Filtering
    workflow_id = request.GET.get('workflow')
    if workflow_id and workflow_id.strip():
        work_items = work_items.filter(workflow_id=workflow_id)
    
    assignee_id = request.GET.get('assignee')
    if assignee_id and assignee_id.strip():
        work_items = work_items.filter(current_assignee_id=assignee_id)
    
    priority = request.GET.get('priority')
    if priority and priority.strip():
        work_items = work_items.filter(priority=priority)
    
    status = request.GET.get('status')
    if status and status.strip():
        if status == 'active':
            work_items = work_items.filter(is_completed=False)
        elif status == 'completed':
            work_items = work_items.filter(is_completed=True)
    
    # Search
    search = request.GET.get('search')
    if search and search.strip() and search.lower() != 'none':
        work_items = work_items.filter(
            Q(title__icontains=search) | 
            Q(description__icontains=search) |
            Q(tags__contains=[search])
        )
    
    # Sorting
    sort = request.GET.get('sort', '-updated_at')
    if sort in ['-updated_at', 'updated_at', 'title', '-title', 'priority', '-priority', 'due_date', '-due_date']:
        work_items = work_items.order_by(sort)
    
    # Pagination
    paginator = Paginator(work_items, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # For API requests, return JSON
    if is_api:
        work_items_data = []
        for item in page_obj.object_list:
            work_items_data.append({
                'id': item.id,
                'title': item.title,
                'workflow': item.workflow.name,
                'priority': item.priority,
                'current_step': item.current_step.name if item.current_step else 'Unknown',
                'assigned_to': item.current_assignee.user.get_full_name() if item.current_assignee and item.current_assignee.user else None,
                'due_date': item.due_date.isoformat() if item.due_date else None,
                'created_at': item.created_at.isoformat(),
                'completed': item.is_completed
            })
        
        return JsonResponse({
            'success': True,
            'work_items': work_items_data,
            'total_count': paginator.count,
            'page_count': paginator.num_pages
        })
    
    # Get filter options
    workflows = Workflow.objects.filter(
        organization=profile.organization, is_active=True
    ).order_by('name')
    
    assignees = UserProfile.objects.filter(
        organization=profile.organization, user__is_active=True
    ).order_by('user__first_name', 'user__last_name')
    
    # Get saved filter views for current user
    saved_filter_views = WorkItemFilterView.objects.filter(user=profile).order_by('name')
    
    # Check if current filters match any saved view
    current_filter_params = WorkItemFilterView.from_request_params(request.GET)
    matching_saved_view = None
    for saved_view in saved_filter_views:
        if saved_view.to_filter_dict() == current_filter_params:
            matching_saved_view = saved_view
            break
    
    context = {
        'profile': profile,
        'page_obj': page_obj,
        'workflows': workflows,
        'assignees': assignees,
        'saved_filter_views': saved_filter_views,
        'matching_saved_view': matching_saved_view,
        'current_filters': {
            'workflow': workflow_id if workflow_id and workflow_id.strip() else '',
            'assignee': assignee_id if assignee_id and assignee_id.strip() else '',
            'priority': priority if priority and priority.strip() else '',
            'status': status if status and status.strip() else '',
            'search': search if search and search.strip() and search.lower() != 'none' else '',
            'sort': sort,
        }
    }
    
    return render(request, 'cflows/work_items_list.html', context)


@login_required
@require_organization_access
@require_POST
def save_filter_view(request):
    """Save current work item filters as a named view"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'success': False, 'error': 'No user profile found'})
    
    # Get filter data from request
    filter_data = WorkItemFilterView.from_request_params(request.POST)
    
    form = SaveFilterViewForm(
        request.POST, 
        user=profile, 
        filter_data=filter_data
    )
    
    if form.is_valid():
        filter_view = form.save()
        return JsonResponse({
            'success': True,
            'filter_view': {
                'id': filter_view.id,
                'name': filter_view.name,
                'is_default': filter_view.is_default
            }
        })
    else:
        return JsonResponse({
            'success': False,
            'errors': form.errors
        })


@login_required
@require_organization_access
@require_POST
def delete_filter_view(request, filter_view_id):
    """Delete a saved filter view"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'success': False, 'error': 'No user profile found'})
    
    try:
        filter_view = WorkItemFilterView.objects.get(
            id=filter_view_id, 
            user=profile
        )
        filter_view.delete()
        return JsonResponse({'success': True})
    except WorkItemFilterView.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Filter view not found'})


@login_required
@require_organization_access
def apply_filter_view(request, filter_view_id):
    """Apply a saved filter view and redirect to work items list"""
    profile = get_user_profile(request)
    if not profile:
        return redirect('cflows:work_items_list')
    
    try:
        filter_view = WorkItemFilterView.objects.get(
            id=filter_view_id, 
            user=profile
        )
        
        # Build query parameters from filter view
        params = {}
        filter_dict = filter_view.to_filter_dict()
        
        for key, value in filter_dict.items():
            if value:  # Only include non-empty values
                params[key] = value
        
        # Build redirect URL with query parameters
        from django.urls import reverse
        from urllib.parse import urlencode
        
        url = reverse('cflows:work_items_list')
        if params:
            url += '?' + urlencode(params)
        
        return redirect(url)
        
    except WorkItemFilterView.DoesNotExist:
        messages.error(request, 'Filter view not found.')
        return redirect('cflows:work_items_list')


@login_required
@require_organization_access
@require_POST
def update_filter_view(request, filter_view_id):
    """Update a saved filter view"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'success': False, 'error': 'No user profile found'})
    
    try:
        filter_view = WorkItemFilterView.objects.get(
            id=filter_view_id, 
            user=profile
        )
        
        form = WorkItemFilterViewForm(
            request.POST, 
            instance=filter_view, 
            user=profile
        )
        
        if form.is_valid():
            form.save()
            return JsonResponse({
                'success': True,
                'filter_view': {
                    'id': filter_view.id,
                    'name': filter_view.name,
                    'is_default': filter_view.is_default
                }
            })
        else:
            return JsonResponse({
                'success': False,
                'errors': form.errors
            })
            
    except WorkItemFilterView.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Filter view not found'})


@login_required
@require_organization_access
@login_required
@require_organization_access
@require_permission('workitem.create')
def create_work_item(request, workflow_id):
    """Create a new work item in a workflow"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'cflows/no_profile.html')
    
    workflow = get_object_or_404(
        Workflow,
        id=workflow_id,
        organization=profile.organization,
        is_active=True
    )
    
    # Get the first step of the workflow
    first_step = workflow.steps.order_by('order').first()
    if not first_step:
        messages.error(request, 'This workflow has no steps defined.')
        return redirect('cflows:workflow_detail', workflow_id=workflow.id)
    
    if request.method == 'POST':
        form = WorkItemForm(request.POST, organization=profile.organization, workflow=workflow)
        if form.is_valid():
            work_item = form.save(commit=False)
            work_item.workflow = workflow
            work_item.current_step = first_step
            work_item.current_step_entered_at = timezone.now()
            work_item.created_by = profile
            work_item.save()
            
            # Save custom fields after the work item is saved
            form.save_custom_fields(work_item)
            
            # Create initial history entry
            WorkItemHistory.objects.create(
                work_item=work_item,
                to_step=first_step,
                changed_by=profile,
                notes="Work item created",
                data_snapshot=work_item.data
            )
            
            # Create revision
            WorkItemRevision.objects.create(
                work_item=work_item,
                revision_number=1,
                title=work_item.title,
                description=work_item.description,
                rich_content=work_item.rich_content,
                data=work_item.data,
                changed_by=profile,
                change_summary="Initial creation"
            )
            
            messages.success(request, f'Work item "{work_item.title}" created successfully!')
            return redirect('cflows:work_item_detail', work_item_id=work_item.id)
        else:
            # Log form errors for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"WorkItem form validation failed: {form.errors}")
            messages.error(request, 'Please correct the errors below.')
    else:
        form = WorkItemForm(organization=profile.organization, workflow=workflow)
    
    # Get custom fields for template display
    from .models import CustomField
    custom_fields = []
    if profile.organization:
        custom_field_objects = CustomField.objects.filter(
            organization=profile.organization,
            is_active=True
        ).filter(
            Q(workflows__isnull=True) | Q(workflows=workflow)
        ).order_by('section', 'order', 'label')
        
        for cf in custom_field_objects:
            field_name = f'custom_{cf.id}'
            if field_name in form.fields:
                custom_fields.append({
                    'field': form[field_name],
                    'section': cf.section or '',
                    'custom_field': cf
                })
    
    context = {
        'profile': profile,
        'workflow': workflow,
        'form': form,
        'custom_fields': custom_fields,
    }
    
    return render(request, 'cflows/create_work_item.html', context)


@login_required
@require_organization_access
def create_work_item_select_workflow(request):
    """Select workflow step for creating a new work item"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'cflows/no_profile.html')
    
    if request.method == 'POST':
        workflow_id = request.POST.get('workflow_id')
        if workflow_id:
            return redirect('cflows:create_work_item', workflow_id=workflow_id)
        else:
            messages.error(request, 'Please select a workflow.')
    
    # Get active workflows for the organization
    workflows = Workflow.objects.filter(
        organization=profile.organization,
        is_active=True
    ).order_by('name')
    
    if not workflows.exists():
        messages.error(request, 'No active workflows found. Create a workflow first.')
        return redirect('cflows:workflow_list')
    
    # If only one workflow, go directly to work item creation
    if workflows.count() == 1:
        return redirect('cflows:create_work_item', workflow_id=workflows.first().id)
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'workflows': workflows,
    }
    
    return render(request, 'cflows/create_work_item_select_workflow.html', context)


@login_required
@require_organization_access
def work_item_detail(request, work_item_id):
    """Detailed view of a work item with comments, attachments, and history"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'cflows/no_profile.html')
    
    work_item = get_object_or_404(
        WorkItem.objects.select_related(
            'workflow', 'current_step', 'current_assignee__user', 'created_by__user'
        ).prefetch_related(
            'attachments__uploaded_by__user',
            'comments__author__user',
            'history__from_step',
            'history__to_step',
            'history__changed_by__user',
            'depends_on',
            'dependents',
            'watchers__user'
        ),
        id=work_item_id,
        workflow__organization=profile.organization
    )
    
    # Available transitions from current step
    available_transitions = work_item.current_step.outgoing_transitions.select_related('to_step')
    
    # Backward transition support
    can_move_backward = work_item.can_move_backward(profile)
    backward_steps = work_item.get_available_backward_steps() if can_move_backward else None
    
    # Handle comment form
    comment_form = None
    if request.method == 'POST':
        if 'add_comment' in request.POST:
            comment_form = WorkItemCommentForm(request.POST)
            if comment_form.is_valid():
                comment = comment_form.save(commit=False)
                comment.work_item = work_item
                comment.author = profile
                comment.save()
                # Parse mentions and notify (mirror logic from attachment_views.add_comment)
                try:
                    from .mention_utils import parse_mentions
                    from core.models import UserProfile as CoreUserProfile, Team as CoreTeam, Notification
                    mentions = parse_mentions(comment.content)
                    # Users
                    if mentions['usernames']:
                        mentioned_users = list(CoreUserProfile.objects.filter(
                            organization=profile.organization,
                            user__username__in=list(mentions['usernames'])
                        ))
                        if mentioned_users:
                            comment.mentioned_users.set(mentioned_users)
                    # Teams
                    if mentions['team_names']:
                        mentioned_teams = list(CoreTeam.objects.filter(
                            organization=profile.organization,
                            name__in=list(mentions['team_names'])
                        ))
                        if mentioned_teams:
                            comment.mentioned_teams.set(mentioned_teams)
                    # Notifications
                    notified_user_ids = set()
                    for u in getattr(comment, 'mentioned_users').all():
                        if u.id != profile.id:
                            notification = Notification.objects.create(
                                recipient=u.user,
                                title=f"You were mentioned on '{work_item.title}'",
                                message=f"{profile.user.get_full_name() or profile.user.username} mentioned you in a comment.",
                                notification_type='info',
                                content_type='WorkItem',
                                object_id=str(work_item.id),
                                action_url=f"/services/cflows/work-items/{work_item.id}/",
                                action_text='View Work Item'
                            )
                            # Trigger email notification
                            from core.notification_views import send_notification_email
                            send_notification_email(notification)
                            notified_user_ids.add(u.id)
                    for team in getattr(comment, 'mentioned_teams').all():
                        for member in team.members.all():
                            if member.id == profile.id:
                                continue
                            if member.id in notified_user_ids:
                                continue
                            notification = Notification.objects.create(
                                recipient=member.user,
                                title=f"Team mention on '{work_item.title}'",
                                message=f"{profile.user.get_full_name() or profile.user.username} mentioned @team:{team.name} in a comment.",
                                notification_type='info',
                                content_type='WorkItem',
                                object_id=str(work_item.id),
                                action_url=f"/services/cflows/work-items/{work_item.id}/",
                                action_text='View Work Item'
                            )
                            # Trigger email notification
                            from core.notification_views import send_notification_email
                            send_notification_email(notification)
                            notified_user_ids.add(member.id)
                except Exception:
                    pass
                messages.success(request, 'Comment added successfully!')
                return redirect('cflows:work_item_detail', work_item_id=work_item.id)
    
    if not comment_form:
        comment_form = WorkItemCommentForm()
    
    # Get comments in thread order
    comments = work_item.comments.filter(parent=None).order_by('created_at')
    
    # Get history
    history = work_item.history.order_by('-created_at')

    # Booking gating / status context
    booking_status = None
    if work_item.current_step and work_item.current_step.requires_booking:
        from services.cflows.models import TeamBooking  # local import to avoid circulars
        step_bookings = TeamBooking.objects.filter(work_item=work_item, workflow_step=work_item.current_step)
        total = step_bookings.count()
        completed = step_bookings.filter(is_completed=True).count()
        remaining = total - completed
        booking_status = {
            'required': True,
            'total': total,
            'completed': completed,
            'remaining': remaining,
            'all_completed': total > 0 and remaining == 0,
            'has_any': total > 0,
            'needs_creation': total == 0,
        }
    else:
        booking_status = {'required': False}
    
    context = {
        'profile': profile,
        'work_item': work_item,
        'available_transitions': available_transitions,
        'can_move_backward': can_move_backward,
        'backward_steps': backward_steps,
        'comment_form': comment_form,
        'comments': comments,
        'history': history,
        'booking_status': booking_status,
        'transfer_check': work_item.can_transfer_to_workflow(profile),
    }
    
    return render(request, 'cflows/work_item_detail.html', context)








@login_required
@require_business_organization
def team_bookings_list(request):
    """List team bookings"""
    profile = request.user.mediap_profile
    
    if not profile:
        return render(request, 'cflows/no_profile.html')
    
    # Get user's teams
    user_teams = profile.teams.filter(is_active=True)
    
    # Check if user has any teams
    if not user_teams.exists():
        messages.warning(request, 
            "You are not a member of any teams. Please contact your administrator to be added to teams to view bookings.")
    
    # Base queryset - bookings for user's teams
    bookings = TeamBooking.objects.filter(
        team__in=user_teams
    ).select_related(
        'team', 'work_item', 'job_type', 'booked_by', 'completed_by'
    )
    
    # Store original count for messaging
    total_team_bookings = bookings.count()
    
    # Filtering
    team_id = request.GET.get('team')
    if team_id:
        bookings = bookings.filter(team_id=team_id)
    
    status_filter = request.GET.get('status')
    if status_filter == 'completed':
        bookings = bookings.filter(is_completed=True)
    elif status_filter == 'upcoming':
        bookings = bookings.filter(is_completed=False, start_time__gte=timezone.now())
    elif status_filter == 'active':
        bookings = bookings.filter(is_completed=False)
    
    # Date filtering
    date_from = request.GET.get('date_from')
    if date_from:
        bookings = bookings.filter(start_time__gte=date_from)
    
    date_to = request.GET.get('date_to')
    if date_to:
        bookings = bookings.filter(end_time__lte=date_to)
    
    bookings = bookings.order_by('-start_time')
    
    # Add helpful messaging for empty results
    if total_team_bookings == 0 and user_teams.exists():
        messages.info(request, 
            "No bookings found for your teams. Your teams may not have any bookings scheduled yet.")
    elif bookings.count() == 0 and total_team_bookings > 0:
        filter_msg = []
        if status_filter:
            filter_msg.append(f"status '{status_filter}'")
        if team_id:
            team_name = user_teams.filter(id=team_id).first()
            if team_name:
                filter_msg.append(f"team '{team_name.name}'")
        if date_from or date_to:
            filter_msg.append("date range")
        
        if filter_msg:
            messages.info(request, 
                f"No bookings found matching your filters ({', '.join(filter_msg)}). "
                f"Try adjusting your filters or select 'All Statuses' to see all {total_team_bookings} available bookings.")
    
    # Pagination
    paginator = Paginator(bookings, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'profile': profile,
        'page_obj': page_obj,
        'bookings': page_obj,
        'user_teams': user_teams,
        'current_filters': {
            'team': team_id,
            'status': status_filter,
            'date_from': date_from,
            'date_to': date_to,
        }
    }
    
    return render(request, 'cflows/team_bookings_list.html', context)


@login_required
@require_business_organization
@require_http_methods(["POST"])
def complete_booking(request, booking_id):
    """Complete a team booking"""
    try:
        profile = request.user.mediap_profile
        booking = get_object_or_404(TeamBooking, id=booking_id, team__members=profile)
        
        if booking.is_completed:
            return JsonResponse({'success': False, 'error': 'Booking is already completed'})
        
        booking.is_completed = True
        booking.completed_at = timezone.now()
        booking.completed_by = profile
        booking.save()

        # Note: External integrations are handled via signals/scheduling integration.
        # Removed stale direct import to non-existent module.

        # If linked to workflow step, progress the work item
        if booking.work_item and booking.workflow_step:
            # This could trigger workflow progression logic
            pass
        
        return JsonResponse({'success': True})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def calendar_view(request):
    """Calendar view with events and bookings"""
    profile = get_user_profile(request)
    
    if not profile:
        return render(request, 'cflows/no_profile.html')
    
    # This would integrate with FullCalendar.js
    # For now, just show a placeholder
    
    context = {
        'profile': profile,
        'organization': profile.organization,
    }
    
    return render(request, 'cflows/calendar.html', context)


# Custom Fields Management Views

@login_required
@require_business_organization
def custom_fields_list(request):
    """List all custom fields for the organization"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    # Check if user is org admin
    if not profile.is_organization_admin:
        messages.error(request, "Only organization admins can manage custom fields.")
        return redirect('cflows:index')
    
    # Get custom fields
    custom_fields = CustomField.objects.filter(
        organization=profile.organization
    ).prefetch_related('workflows', 'workflow_steps').order_by('section', 'order', 'label')
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'custom_fields': custom_fields,
    }
    
    return render(request, 'cflows/custom_fields_list.html', context)


@login_required
@require_business_organization
@require_permission('customfields.manage')
def create_custom_field(request):
    """Create a new custom field"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    # Check if user is org admin
    if not profile.is_organization_admin:
        messages.error(request, "Only organization admins can manage custom fields.")
        return redirect('cflows:index')
    
    if request.method == 'POST':
        form = CustomFieldForm(request.POST, organization=profile.organization)
        if form.is_valid():
            custom_field = form.save(commit=False)
            custom_field.organization = profile.organization
            custom_field.save()
            form.save_m2m()  # Save many-to-many relationships
            messages.success(request, f"Custom field '{custom_field.label}' created successfully.")
            return redirect('cflows:custom_fields_list')
    else:
        form = CustomFieldForm(organization=profile.organization)
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'form': form,
        'title': 'Create Custom Field'
    }
    
    return render(request, 'cflows/custom_field_form.html', context)


@login_required
@require_business_organization
@require_permission('customfields.manage')
def edit_custom_field(request, field_id):
    """Edit an existing custom field"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    # Check if user is org admin
    if not profile.is_organization_admin:
        messages.error(request, "Only organization admins can manage custom fields.")
        return redirect('cflows:index')
    
    custom_field = get_object_or_404(
        CustomField,
        id=field_id,
        organization=profile.organization
    )
    
    if request.method == 'POST':
        form = CustomFieldForm(request.POST, instance=custom_field, organization=profile.organization)
        if form.is_valid():
            form.save()
            messages.success(request, f"Custom field '{custom_field.label}' updated successfully.")
            return redirect('cflows:custom_fields_list')
    else:
        form = CustomFieldForm(instance=custom_field, organization=profile.organization)
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'form': form,
        'custom_field': custom_field,
        'title': 'Edit Custom Field'
    }
    
    return render(request, 'cflows/custom_field_form.html', context)


@login_required
@require_business_organization
@require_POST
@require_permission('customfields.manage')
def delete_custom_field(request, field_id):
    """Delete a custom field"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    # Check if user is org admin
    if not profile.is_organization_admin:
        messages.error(request, "Only organization admins can manage custom fields.")
        return redirect('cflows:index')
    
    custom_field = get_object_or_404(
        CustomField,
        id=field_id,
        organization=profile.organization
    )
    
    # Check if field has any values
    value_count = WorkItemCustomFieldValue.objects.filter(custom_field=custom_field).count()
    
    if value_count > 0:
        messages.warning(
            request, 
            f"Custom field '{custom_field.label}' has {value_count} values and cannot be deleted. "
            "You can deactivate it instead."
        )
    else:
        field_label = custom_field.label
        custom_field.delete()
        messages.success(request, f"Custom field '{field_label}' deleted successfully.")
    
    return redirect('cflows:custom_fields_list')


@login_required
@require_business_organization
@require_POST  
def toggle_custom_field(request, field_id):
    """Toggle active status of a custom field"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    # Check if user is org admin
    if not profile.is_organization_admin:
        messages.error(request, "Only organization admins can manage custom fields.")
        return redirect('cflows:index')
    
    custom_field = get_object_or_404(
        CustomField,
        id=field_id,
        organization=profile.organization
    )
    
    custom_field.is_active = not custom_field.is_active
    custom_field.save()
    
    status = "activated" if custom_field.is_active else "deactivated"
    messages.success(request, f"Custom field '{custom_field.label}' {status}.")
    
    return redirect('cflows:custom_fields_list')


# Team Management Views

@login_required
@require_business_organization
def teams_list(request):
    """List all teams for the organization"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    # Check if user is org admin or has staff access
    if not (profile.is_organization_admin or profile.has_staff_panel_access):
        messages.error(request, "You don't have permission to manage teams.")
        return redirect('cflows:index')
    
    # Get teams with member count, organized by hierarchy
    all_teams = Team.objects.filter(
        organization=profile.organization
    ).prefetch_related('members__user', 'sub_teams').annotate(
        members_count=models.Count('members')
    ).order_by('name')
    
    # Separate top-level teams and organize into hierarchy
    top_level_teams = all_teams.filter(parent_team__isnull=True)
    
    # Create a hierarchical structure for display
    def build_team_hierarchy(team):
        team_data = {
            'team': team,
            'sub_teams': []
        }
        for sub_team in team.sub_teams.all():
            team_data['sub_teams'].append(build_team_hierarchy(sub_team))
        return team_data
    
    hierarchical_teams = [build_team_hierarchy(team) for team in top_level_teams]
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'teams': all_teams,  # Keep for backward compatibility
        'hierarchical_teams': hierarchical_teams,
        'total_teams': all_teams.count(),
        'top_level_teams_count': top_level_teams.count(),
    }
    
    return render(request, 'cflows/teams_list.html', context)


@login_required
@require_business_organization
@require_permission('team.create')
def create_team(request):
    """Create a new team"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    # Check if user is org admin or has staff access
    if not (profile.is_organization_admin or profile.has_staff_panel_access):
        messages.error(request, "You don't have permission to create teams.")
        return redirect('cflows:index')
    
    # Get parent team if specified
    parent_team_id = request.GET.get('parent')
    parent_team = None
    if parent_team_id:
        try:
            parent_team = Team.objects.get(
                id=parent_team_id,
                organization=profile.organization
            )
        except Team.DoesNotExist:
            messages.error(request, "Parent team not found.")
            return redirect('cflows:teams_list')
    
    if request.method == 'POST':
        form = TeamForm(request.POST, organization=profile.organization)
        if form.is_valid():
            team = form.save(commit=False)
            team.organization = profile.organization
            team.created_by = profile
            team.save()
            
            team_type = "sub-team" if team.parent_team else "team"
            messages.success(request, f"{team_type.title()} '{team.name}' created successfully!")
            return redirect('cflows:teams_list')
    else:
        initial_data = {}
        if parent_team:
            initial_data['parent_team'] = parent_team
        form = TeamForm(organization=profile.organization, initial=initial_data)
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'form': form,
        'parent_team': parent_team,
        'title': f'Create {"Sub-team" if parent_team else "Team"}' + (f' under {parent_team.name}' if parent_team else '')
    }
    
    return render(request, 'cflows/team_form.html', context)


@login_required
@require_business_organization
@require_permission('team.edit')
def edit_team(request, team_id):
    """Edit an existing team"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    # Check if user is org admin or has staff access
    if not (profile.is_organization_admin or profile.has_staff_panel_access):
        messages.error(request, "You don't have permission to edit teams.")
        return redirect('cflows:index')
    
    team = get_object_or_404(
        Team,
        id=team_id,
        organization=profile.organization
    )
    
    if request.method == 'POST':
        form = TeamForm(request.POST, instance=team, organization=profile.organization, current_team=team)
        if form.is_valid():
            form.save()
            messages.success(request, f"Team '{team.name}' updated successfully!")
            return redirect('cflows:teams_list')
    else:
        form = TeamForm(instance=team, organization=profile.organization, current_team=team)
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'form': form,
        'team': team,
        'title': f'Edit Team: {team.name}'
    }
    
    return render(request, 'cflows/team_form.html', context)


@login_required
@require_business_organization
def team_detail(request, team_id):
    """Detailed view of a team with member management"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    team = get_object_or_404(
        Team,
        id=team_id,
        organization=profile.organization
    )
    
    # Get team members
    team_members = team.members.select_related('user').order_by('user__first_name', 'user__last_name')
    
    # Get available users to add to team (org members not already in team)
    available_users = UserProfile.objects.filter(
        organization=profile.organization,
        user__is_active=True
    ).exclude(
        id__in=team_members.values_list('id', flat=True)
    ).select_related('user').order_by('user__first_name', 'user__last_name')
    
    # Handle adding/removing team members
    if request.method == 'POST':
        if 'add_member' in request.POST:
            user_id = request.POST.get('user_id')
            if user_id:
                try:
                    user_profile = UserProfile.objects.get(
                        id=user_id,
                        organization=profile.organization,
                        user__is_active=True
                    )
                    team.members.add(user_profile)
                    messages.success(request, f"Added {user_profile.user.get_full_name() or user_profile.user.username} to the team.")
                except UserProfile.DoesNotExist:
                    messages.error(request, "User not found.")
            return redirect('cflows:team_detail', team_id=team.id)
        
        elif 'remove_member' in request.POST:
            user_id = request.POST.get('user_id')
            if user_id:
                try:
                    user_profile = UserProfile.objects.get(
                        id=user_id,
                        organization=profile.organization
                    )
                    team.members.remove(user_profile)
                    messages.success(request, f"Removed {user_profile.user.get_full_name() or user_profile.user.username} from the team.")
                except UserProfile.DoesNotExist:
                    messages.error(request, "User not found.")
            return redirect('cflows:team_detail', team_id=team.id)
    
    # Get team statistics
    from .models import TeamBooking
    stats = {
        'total_bookings': TeamBooking.objects.filter(team=team).count(),
        'active_bookings': TeamBooking.objects.filter(team=team, is_completed=False).count(),
        'completed_bookings': TeamBooking.objects.filter(team=team, is_completed=True).count(),
        'member_count': team_members.count(),
    }
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'team': team,
        'team_members': team_members,
        'available_users': available_users,
        'stats': stats,
        'can_manage': profile.is_organization_admin or profile.has_staff_panel_access,
    }
    
    return render(request, 'cflows/team_detail.html', context)


@login_required
@require_business_organization
def create_workflow_enhanced(request):
    """Enhanced workflow creation with step creation"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    # Check if user is org admin or has staff access
    if not (profile.is_organization_admin or profile.has_staff_panel_access):
        messages.error(request, "You don't have permission to create workflows.")
        return redirect('cflows:index')
    
    if request.method == 'POST':
        form = WorkflowCreationForm(request.POST, organization=profile.organization)
        if form.is_valid():
            workflow = form.save(commit=True, created_by=profile)
            messages.success(request, f"Workflow '{workflow.name}' created successfully with {workflow.steps.count()} steps!")
            return redirect('cflows:workflow_detail', workflow_id=workflow.id)
    else:
        form = WorkflowCreationForm(organization=profile.organization)
    
    # Get available teams for step assignment
    teams = Team.objects.filter(
        organization=profile.organization,
        is_active=True
    ).order_by('name')
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'form': form,
        'teams': teams,
        'title': 'Create New Workflow'
    }
    
    return render(request, 'cflows/create_workflow_enhanced.html', context)


@login_required
@require_business_organization
def workflow_transitions_manager(request, workflow_id):
    """Visual workflow transition manager"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    workflow = get_object_or_404(
        Workflow, 
        id=workflow_id, 
        organization=profile.organization
    )
    
    # Check permissions
    if not (profile.is_organization_admin or profile.has_staff_panel_access):
        messages.error(request, "You don't have permission to manage workflow transitions.")
        return redirect('cflows:workflow_detail', workflow_id=workflow_id)
    
    steps = workflow.steps.order_by('order')
    transitions = WorkflowTransition.objects.filter(
        from_step__workflow=workflow
    ).select_related('from_step', 'to_step')
    
    # Create transition matrix for visualization
    transition_matrix = {}
    transition_matrix_list = []
    for step in steps:
        matrix_data = {
            'step': step,
            'outgoing': transitions.filter(from_step=step),
            'incoming': transitions.filter(to_step=step)
        }
        transition_matrix[step.id] = matrix_data
        transition_matrix_list.append(matrix_data)
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'workflow': workflow,
        'steps': steps,
        'transitions': transitions,
        'transition_matrix': transition_matrix,
        'transition_matrix_list': transition_matrix_list,
        'title': f'Manage Transitions - {workflow.name}'
    }
    
    return render(request, 'cflows/workflow_transitions_manager.html', context)


@login_required
@require_business_organization
def create_workflow_transition(request, workflow_id, from_step_id):
    """Create a new workflow transition from a specific step"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    workflow = get_object_or_404(
        Workflow, 
        id=workflow_id, 
        organization=profile.organization
    )
    
    from_step = get_object_or_404(
        WorkflowStep,
        id=from_step_id,
        workflow=workflow
    )
    
    # Check permissions
    if not (profile.is_organization_admin or profile.has_staff_panel_access):
        messages.error(request, "You don't have permission to create workflow transitions.")
        return redirect('cflows:workflow_detail', workflow_id=workflow_id)
    
    if request.method == 'POST':
        form = WorkflowTransitionForm(
            request.POST, 
            workflow=workflow, 
            from_step=from_step
        )
        if form.is_valid():
            transition = form.save(commit=False)
            transition.from_step = from_step
            transition.save()
            
            messages.success(request, f"Transition created from '{from_step.name}' to '{transition.to_step.name}'")
            return redirect('cflows:workflow_transitions_manager', workflow_id=workflow_id)
    else:
        form = WorkflowTransitionForm(workflow=workflow, from_step=from_step)
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'workflow': workflow,
        'from_step': from_step,
        'form': form,
        'title': f'Create Transition from {from_step.name}'
    }
    
    return render(request, 'cflows/create_workflow_transition.html', context)


@login_required
@require_business_organization
def edit_workflow_transition(request, transition_id):
    """Edit an existing workflow transition"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    transition = get_object_or_404(WorkflowTransition, id=transition_id)
    workflow = transition.from_step.workflow
    
    # Check organization access
    if workflow.organization != profile.organization:
        messages.error(request, "You don't have access to this workflow.")
        return redirect('cflows:index')
    
    # Check permissions
    if not (profile.is_organization_admin or profile.has_staff_panel_access):
        messages.error(request, "You don't have permission to edit workflow transitions.")
        return redirect('cflows:workflow_detail', workflow_id=workflow.id)
    
    if request.method == 'POST':
        form = WorkflowTransitionForm(
            request.POST, 
            instance=transition,
            workflow=workflow, 
            from_step=transition.from_step
        )
        if form.is_valid():
            form.save()
            messages.success(request, f"Transition updated successfully")
            return redirect('cflows:workflow_transitions_manager', workflow_id=workflow.id)
    else:
        form = WorkflowTransitionForm(
            instance=transition,
            workflow=workflow, 
            from_step=transition.from_step
        )
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'workflow': workflow,
        'transition': transition,
        'form': form,
        'title': f'Edit Transition: {transition.from_step.name} → {transition.to_step.name}'
    }
    
    return render(request, 'cflows/edit_workflow_transition.html', context)


@login_required
@require_business_organization
@require_http_methods(["POST"])
def delete_workflow_transition(request, transition_id):
    """Delete a workflow transition"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return JsonResponse({'success': False, 'error': 'Authentication required'})
    
    transition = get_object_or_404(WorkflowTransition, id=transition_id)
    workflow = transition.from_step.workflow
    
    # Check organization access
    if workflow.organization != profile.organization:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    # Check permissions
    if not (profile.is_organization_admin or profile.has_staff_panel_access):
        return JsonResponse({'success': False, 'error': 'Permission denied'})
    
    try:
        from_step_name = transition.from_step.name
        to_step_name = transition.to_step.name
        transition.delete()
        
        return JsonResponse({
            'success': True, 
            'message': f"Transition from '{from_step_name}' to '{to_step_name}' deleted successfully"
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_business_organization
def bulk_create_transitions(request, workflow_id):
    """Create multiple transitions at once using patterns"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    workflow = get_object_or_404(
        Workflow, 
        id=workflow_id, 
        organization=profile.organization
    )
    
    # Check permissions
    if not (profile.is_organization_admin or profile.has_staff_panel_access):
        messages.error(request, "You don't have permission to create workflow transitions.")
        return redirect('cflows:workflow_detail', workflow_id=workflow_id)
    
    if request.method == 'POST':
        form = BulkTransitionForm(request.POST, workflow=workflow)
        if form.is_valid():
            transitions_created = form.create_transitions()
            
            if transitions_created:
                messages.success(
                    request, 
                    f"Successfully created {len(transitions_created)} transitions using {form.cleaned_data['transition_type']} pattern"
                )
            else:
                messages.info(request, "No new transitions were created (they may already exist)")
            
            return redirect('cflows:workflow_transitions_manager', workflow_id=workflow_id)
    else:
        form = BulkTransitionForm(workflow=workflow)
    
    # Get current transition count for display
    current_transitions = WorkflowTransition.objects.filter(
        from_step__workflow=workflow
    ).count()
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'workflow': workflow,
        'form': form,
        'current_transitions': current_transitions,
        'steps_count': workflow.steps.count(),
        'title': f'Bulk Create Transitions - {workflow.name}'
    }
    
    return render(request, 'cflows/bulk_create_transitions.html', context)


@login_required
@require_business_organization
def select_workflow_for_transitions(request):
    """Select a workflow to manage transitions for (navbar quick access)"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    # Check permissions
    if not (profile.is_organization_admin or profile.has_staff_panel_access):
        messages.error(request, "You don't have permission to manage workflow transitions.")
        return redirect('cflows:index')
    
    if request.method == 'POST':
        workflow_id = request.POST.get('workflow_id')
        if workflow_id:
            return redirect('cflows:workflow_transitions_manager', workflow_id=workflow_id)
        else:
            messages.error(request, 'Please select a workflow.')
    
    # Get active workflows for the organization
    workflows = Workflow.objects.filter(
        organization=profile.organization,
        is_active=True
    ).annotate(
        steps_count=Count('steps'),
        transitions_count=Count('steps__outgoing_transitions', distinct=True)
    ).order_by('name')
    
    if not workflows.exists():
        messages.error(request, 'No active workflows found. Create a workflow first.')
        return redirect('cflows:workflow_list')
    
    # If only one workflow, go directly to transition management
    if workflows.count() == 1:
        return redirect('cflows:workflow_transitions_manager', workflow_id=workflows.first().id)
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'workflows': workflows,
        'title': 'Select Workflow - Manage Transitions',
        'action': 'manage transitions'
    }
    
    return render(request, 'cflows/select_workflow_for_action.html', context)


@login_required
@require_business_organization
def select_workflow_for_bulk_transitions(request):
    """Select workflow for bulk transitions creation"""
    profile = get_user_profile(request)
    if not profile:
        return redirect('accounts:create_profile')
    
    workflows = Workflow.objects.filter(organization=profile.organization)
    
    context = {
        'workflows': workflows,
        'page_title': 'Select Workflow for Bulk Transitions',
        'action_title': 'Create Bulk Transitions',
        'action_url_name': 'cflows:bulk_create_transitions',
        'action_description': 'Create multiple transitions at once for the selected workflow.'
    }
    return render(request, 'cflows/select_workflow_for_action.html', context)


@login_required
@require_organization_access
@require_GET
def mention_suggestions(request):
    """Return mention suggestions for users and teams in the current organization.
    Query params: q (string)
    """
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'success': False, 'error': 'No profile'}, status=403)
    q = (request.GET.get('q') or '').strip()
    users_qs = UserProfile.objects.filter(
        organization=profile.organization,
        user__is_active=True
    ).select_related('user')
    teams_qs = Team.objects.filter(
        organization=profile.organization,
        is_active=True
    )
    if q:
        users_qs = users_qs.filter(
            models.Q(user__username__icontains=q) |
            models.Q(user__first_name__icontains=q) |
            models.Q(user__last_name__icontains=q)
        )
        teams_qs = teams_qs.filter(name__icontains=q)
    users = [
        {
            'type': 'user',
            'id': up.id,
            'username': up.user.username,
            'name': up.user.get_full_name() or up.user.username
        }
        for up in users_qs.order_by('user__first_name', 'user__last_name')[:10]
    ]
    teams = [
        {
            'type': 'team',
            'id': t.id,
            'name': t.name
        }
        for t in teams_qs.order_by('name')[:10]
    ]
    return JsonResponse({'success': True, 'users': users, 'teams': teams})


@login_required
@require_organization_access
def create_booking_from_work_item(request, work_item_id):
    """Create a booking from any work item (CFlows or Scheduling service)"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'cflows/no_profile.html')
    
    work_item = get_object_or_404(
        WorkItem,
        id=work_item_id,
        workflow__organization=profile.organization
    )
    
    if request.method == 'POST':
        form = SchedulingBookingForm(
            request.POST,
            organization=profile.organization,
            work_item=work_item
        )
        if form.is_valid():
            try:
                booking_result = form.save_booking(profile)
                
                if booking_result['type'] == 'cflows':
                    messages.success(
                        request, 
                        f'CFlows booking "{booking_result["booking"].title}" created successfully!'
                    )
                else:
                    messages.success(
                        request, 
                        f'Scheduling service booking "{booking_result["booking"].title}" created successfully!'
                    )
                
                # Add parameter to show booking creation success on work item detail
                return redirect(f'{booking_result["redirect_url"]}?booking_created=1')
                
            except Exception as e:
                messages.error(request, f'Error creating booking: {str(e)}')
    else:
        form = SchedulingBookingForm(
            organization=profile.organization,
            work_item=work_item
        )
    
    # Get existing bookings for this work item to show context
    cflows_bookings = TeamBooking.objects.filter(work_item=work_item).select_related('team')
    
    # Get scheduling service bookings for this work item
    scheduling_bookings = []
    try:
        from services.scheduling.models import BookingRequest
        from django.db.models import Q
        scheduling_bookings = BookingRequest.objects.filter(
            Q(source_service='cflows', source_object_type='WorkItem', source_object_id=str(work_item.id)) |
            Q(custom_data__work_item_id=work_item.id) |
            Q(custom_data__work_item_id=str(work_item.id))
        ).select_related('resource')
    except ImportError:
        pass  # Scheduling service not available
    
    context = {
        'profile': profile,
        'work_item': work_item,
        'form': form,
        'cflows_bookings': cflows_bookings,
        'scheduling_bookings': scheduling_bookings,
        'title': f'Create Booking - {work_item.title}'
    }
    
    return render(request, 'cflows/create_booking_from_work_item.html', context)


@login_required
@require_organization_access 
def work_item_bookings_status(request, work_item_id):
    """Get booking status for a work item (used for AJAX updates)"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'error': 'No profile found'}, status=403)
    
    work_item = get_object_or_404(
        WorkItem,
        id=work_item_id,
        workflow__organization=profile.organization
    )
    
    # Get user's teams for filtering
    user_teams = profile.teams.filter(is_active=True)
    
    # Get CFlows bookings - only for teams the user is a member of
    cflows_bookings = TeamBooking.objects.filter(
        work_item=work_item,
        team__in=user_teams
    ).select_related('team')
    
    # Count total bookings for this work item (for debugging/messaging)
    total_cflows_bookings = TeamBooking.objects.filter(work_item=work_item).count()
    
    cflows_data = []
    for booking in cflows_bookings:
        cflows_data.append({
            'id': booking.id,
            'title': booking.title,
            'team': booking.team.name if booking.team else 'No Team',
            'start_time': booking.start_time.isoformat(),
            'end_time': booking.end_time.isoformat(),
            'is_completed': booking.is_completed,
            'view_url': f'/services/cflows/calendar/bookings/{booking.id}/',
            'type': 'cflows'
        })
    
    # Get Scheduling service bookings
    scheduling_data = []
    try:
        from services.scheduling.models import BookingRequest
        from django.db.models import Q
        scheduling_bookings = BookingRequest.objects.filter(
            Q(source_service='cflows', source_object_type='WorkItem', source_object_id=str(work_item.id)) |
            Q(custom_data__work_item_id=work_item.id) |
            Q(custom_data__work_item_id=str(work_item.id))
        ).select_related('resource')
        
        for booking in scheduling_bookings:
            scheduling_data.append({
                'id': booking.id,
                'uuid': str(booking.uuid),
                'title': booking.title,
                'resource': booking.resource.name if booking.resource else 'No Resource',
                'requested_start': booking.requested_start.isoformat(),
                'requested_end': booking.requested_end.isoformat(),
                'status': booking.status,
                'view_url': f'/services/scheduling/bookings/{booking.id}/',
                'complete_url': f'/services/scheduling/bookings/{booking.uuid}/complete/',
                'type': 'scheduling'
            })
    except ImportError:
        pass  # Scheduling service not available
    
    return JsonResponse({
        'work_item_id': work_item.id,
        'work_item_title': work_item.title,
        'cflows_bookings': cflows_data,
        'scheduling_bookings': scheduling_data,
        'total_bookings': len(cflows_data) + len(scheduling_data),
        'has_bookings': bool(cflows_data or scheduling_data),
        'user_teams_count': user_teams.count(),
        'total_cflows_bookings': total_cflows_bookings,
        'visible_cflows_bookings': len(cflows_data),
        'hidden_cflows_bookings': total_cflows_bookings - len(cflows_data)
    })


@login_required
@require_organization_access
def work_item_booking_summary(request, work_item_id):
    """Get a summary of bookings for display in work item detail"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'error': 'No profile found'}, status=403)
    
    work_item = get_object_or_404(
        WorkItem,
        id=work_item_id,
        workflow__organization=profile.organization
    )
    
    # Count CFlows bookings
    cflows_total = TeamBooking.objects.filter(work_item=work_item).count()
    cflows_completed = TeamBooking.objects.filter(work_item=work_item, is_completed=True).count()
    
    # Count Scheduling service bookings
    scheduling_total = 0
    scheduling_completed = 0
    try:
        from services.scheduling.models import BookingRequest
        from django.db.models import Q
        scheduling_q = (
            Q(source_service='cflows', source_object_type='WorkItem', source_object_id=str(work_item.id)) |
            Q(custom_data__work_item_id=work_item.id) |
            Q(custom_data__work_item_id=str(work_item.id))
        )
        scheduling_total = BookingRequest.objects.filter(scheduling_q).count()
        scheduling_completed = BookingRequest.objects.filter(scheduling_q, status='completed').count()
    except ImportError:
        pass
    
    total_bookings = cflows_total + scheduling_total
    total_completed = cflows_completed + scheduling_completed
    
    return JsonResponse({
        'total_bookings': total_bookings,
        'completed_bookings': total_completed,
        'pending_bookings': total_bookings - total_completed,
        'has_bookings': total_bookings > 0,
        'cflows_bookings': {
            'total': cflows_total,
            'completed': cflows_completed
        },
        'scheduling_bookings': {
            'total': scheduling_total,
            'completed': scheduling_completed
        }
    })


@login_required
@require_organization_access
def view_work_item_bookings(request, work_item_id):
    """Navigate to view all bookings for a work item (both CFlows and Scheduling)"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'cflows/no_profile.html')
    
    work_item = get_object_or_404(
        WorkItem,
        id=work_item_id,
        workflow__organization=profile.organization
    )
    
    # Get user's teams for filtering
    user_teams = profile.teams.filter(is_active=True)
    
    # Get CFlows bookings - only for teams the user is a member of
    cflows_bookings = TeamBooking.objects.filter(
        work_item=work_item,
        team__in=user_teams
    ).select_related('team', 'booked_by', 'completed_by')
    
    # Count total bookings for this work item (for messaging)
    total_bookings = TeamBooking.objects.filter(work_item=work_item).count()
    
    # Get Scheduling service bookings
    scheduling_bookings = []
    try:
        from services.scheduling.models import BookingRequest
        from django.db.models import Q
        scheduling_bookings = BookingRequest.objects.filter(
            Q(source_service='cflows', source_object_type='WorkItem', source_object_id=str(work_item.id)) |
            Q(custom_data__work_item_id=work_item.id) |
            Q(custom_data__work_item_id=str(work_item.id))
        ).select_related('resource')
    except ImportError:
        pass  # Scheduling service not available
    
    # Add messaging for empty results
    from django.contrib import messages
    if not user_teams.exists():
        messages.warning(request, 
            "You are not a member of any teams. Contact your administrator to be added to teams to view bookings.")
    elif total_bookings > 0 and not cflows_bookings.exists():
        messages.info(request, 
            f"This work item has {total_bookings} booking(s), but they were made by teams you don't have access to. "
            f"Contact your administrator if you need access to these bookings.")
    elif not cflows_bookings.exists() and not scheduling_bookings:
        messages.info(request, "No bookings found for this work item.")
    
    context = {
        'profile': profile,
        'work_item': work_item,
        'cflows_bookings': cflows_bookings,
        'scheduling_bookings': scheduling_bookings,
        'title': f'Bookings for {work_item.title}',
        'user_teams_count': user_teams.count(),
        'total_bookings': total_bookings,
        'visible_bookings': cflows_bookings.count(),
    }
    
    return render(request, 'cflows/work_item_bookings.html', context)


@login_required
@require_organization_access  
def redirect_to_scheduling_bookings(request, work_item_id):
    """Redirect to scheduling service with filters for this work item"""
    profile = get_user_profile(request)
    if not profile:
        return redirect('cflows:work_items_list')
    
    work_item = get_object_or_404(
        WorkItem,
        id=work_item_id,
        workflow__organization=profile.organization
    )
    
    # Construct URL with filters for this work item
    from django.urls import reverse
    from urllib.parse import urlencode
    
    base_url = reverse('scheduling:booking_list')
    params = {
        'source_service': 'cflows',
        'source_object_id': str(work_item.id),
        'work_item_title': work_item.title
    }
    
    redirect_url = f"{base_url}?{urlencode(params)}"
    return redirect(redirect_url)


def select_workflow_for_bulk_transitions(request):
    """Select a workflow for bulk transition creation (navbar quick access)"""
    profile = get_user_profile(request)
    if not profile or not profile.organization:
        return redirect('cflows:index')
    
    # Check permissions
    if not (profile.is_organization_admin or profile.has_staff_panel_access):
        messages.error(request, "You don't have permission to create workflow transitions.")
        return redirect('cflows:index')
    
    if request.method == 'POST':
        workflow_id = request.POST.get('workflow_id')
        if workflow_id:
            return redirect('cflows:bulk_create_transitions', workflow_id=workflow_id)
        else:
            messages.error(request, 'Please select a workflow.')
    
    # Get active workflows for the organization with steps
    workflows = Workflow.objects.filter(
        organization=profile.organization,
        is_active=True
    ).annotate(
        steps_count=Count('steps'),
        transitions_count=Count('steps__outgoing_transitions', distinct=True)
    ).filter(
        steps_count__gt=1  # Only show workflows with multiple steps
    ).order_by('name')
    
    if not workflows.exists():
        messages.error(request, 'No workflows with multiple steps found. Create workflows with steps first.')
        return redirect('cflows:workflow_list')
    
    # If only one workflow, go directly to bulk transition creation
    if workflows.count() == 1:
        return redirect('cflows:bulk_create_transitions', workflow_id=workflows.first().id)
    
    context = {
        'profile': profile,
        'organization': profile.organization,
        'workflows': workflows,
        'title': 'Select Workflow - Bulk Create Transitions',
        'action': 'create bulk transitions'
    }
    
    return render(request, 'cflows/select_workflow_for_action.html', context)


@login_required
@require_organization_access
def transfer_work_item(request, uuid):
    """Transfer a work item to a different workflow"""
    profile = get_user_profile(request)
    if not profile:
        messages.error(request, "Profile not found")
        return redirect('cflows:index')
    
    work_item = get_object_or_404(WorkItem, uuid=uuid, workflow__organization=profile.organization)
    
    # Check if user can transfer this work item
    transfer_check = work_item.can_transfer_to_workflow(profile)
    if not transfer_check['can_transfer']:
        messages.error(request, f"You cannot transfer this work item: {'; '.join(transfer_check['reasons'])}")
        return redirect('cflows:work_item_detail', work_item_id=work_item.id)
    
    # Get available destination workflows (exclude current workflow)
    available_workflows = Workflow.objects.filter(
        organization=profile.organization,
        is_active=True
    ).exclude(id=work_item.workflow.id).select_related('owner_team')
    
    # Filter workflows user has access to
    if not profile.is_organization_admin:
        available_workflows = available_workflows.filter(
            owner_team__in=profile.teams.all()
        )
    
    if request.method == 'POST':
        destination_workflow_id = request.POST.get('destination_workflow')
        destination_step_id = request.POST.get('destination_step')
        transfer_notes = request.POST.get('transfer_notes', '').strip()
        preserve_assignee = request.POST.get('preserve_assignee') == 'on'
        
        if not destination_workflow_id or not destination_step_id:
            messages.error(request, "Please select both destination workflow and step")
            return redirect('cflows:transfer_work_item', uuid=uuid)
        
        try:
            destination_workflow = Workflow.objects.get(
                id=destination_workflow_id,
                organization=profile.organization,
                is_active=True
            )
            destination_step = WorkflowStep.objects.get(
                id=destination_step_id,
                workflow=destination_workflow
            )
            
            # Final permission check for destination workflow
            dest_check = work_item.can_transfer_to_workflow(profile, destination_workflow)
            if not dest_check['can_transfer']:
                messages.error(request, f"Cannot transfer to selected workflow: {'; '.join(dest_check['reasons'])}")
                return redirect('cflows:transfer_work_item', uuid=uuid)
            
            # Perform the transfer
            with transaction.atomic():
                result = work_item.transfer_to_workflow(
                    destination_workflow=destination_workflow,
                    destination_step=destination_step,
                    transferred_by=profile,
                    notes=transfer_notes,
                    preserve_assignee=preserve_assignee
                )
            
            if result['success']:
                for message in result['messages']:
                    messages.success(request, message)
                return redirect('cflows:work_item_detail', work_item_id=work_item.id)
            else:
                messages.error(request, result.get('error', 'Transfer failed'))
                
        except (Workflow.DoesNotExist, WorkflowStep.DoesNotExist):
            messages.error(request, "Invalid destination workflow or step")
        except Exception as e:
            messages.error(request, f"Transfer failed: {str(e)}")
        
        return redirect('cflows:transfer_work_item', uuid=uuid)
    
    # GET request - show transfer form
    context = {
        'profile': profile,
        'organization': profile.organization,
        'work_item': work_item,
        'available_workflows': available_workflows,
        'transfer_check': transfer_check,
        'page_title': f'Transfer Work Item: {work_item.title}',
    }
    
    return render(request, 'cflows/transfer_work_item.html', context)


@login_required
@require_organization_access
def get_workflow_steps_api(request, workflow_id):
    """API endpoint to get steps for a specific workflow (for transfer form)"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'error': 'Profile not found'}, status=400)
    
    try:
        workflow = Workflow.objects.get(
            id=workflow_id,
            organization=profile.organization
        )
        
        # Check if user has access to this workflow
        if not profile.is_organization_admin and workflow.owner_team not in profile.teams.all():
            return JsonResponse({'error': 'No access to this workflow'}, status=403)
        
        steps = workflow.steps.order_by('order').values(
            'id', 'name', 'description', 'is_terminal', 'requires_booking'
        )
        
        return JsonResponse({'steps': list(steps)})
        
    except Workflow.DoesNotExist:
        return JsonResponse({'error': 'Workflow not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def debug_user_info(request):
    """Debug API endpoint to check user authentication and organization"""
    profile = get_user_profile(request)
    
    return JsonResponse({
        'user': request.user.username if request.user.is_authenticated else 'Anonymous',
        'user_id': request.user.id if request.user.is_authenticated else None,
        'profile': str(profile) if profile else None,
        'organization': profile.organization.name if profile and profile.organization else None,
        'organization_id': profile.organization.id if profile and profile.organization else None,
        'is_org_admin': profile.is_organization_admin if profile else False,
        'teams': [str(team) for team in profile.teams.all()] if profile else [],
        'session_key': request.session.session_key,
        'headers': dict(request.headers),
    })

