"""
CFlows Work Item Transition Views
Handles moving work items through workflow steps
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.utils import timezone
from django.db import transaction
from django.urls import reverse
from core.models import Organization, UserProfile, Team
from core.views import require_organization_access
from core.decorators import require_permission
from .models import (
    Workflow, WorkflowStep, WorkflowTransition, 
    WorkItem, WorkItemHistory, WorkItemComment, 
    TeamBooking
)
from .forms import WorkItemCommentForm
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
@require_permission('workitem.transition')
@require_POST
def transition_work_item(request, work_item_id, transition_id):
    """Move a work item to the next step via a specific transition"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'success': False, 'error': 'No user profile found'})
    
    work_item = get_object_or_404(
        WorkItem.objects.select_related('workflow', 'current_step'),
        id=work_item_id,
        workflow__organization=profile.organization
    )
    
    transition = get_object_or_404(
        WorkflowTransition.objects.select_related('from_step', 'to_step'),
        id=transition_id,
        from_step=work_item.current_step
    )
    
    # Check if user has permission to make this transition
    # For now, any organization member can transition items
    # TODO: Add more granular permissions based on team membership or roles
    
    notes = request.POST.get('notes', '')
    
    try:
        # BLOCK FORWARD PROGRESSION IF CURRENT STEP REQUIRES BOOKING THAT IS NOT COMPLETED
        current_step = work_item.current_step
        if current_step.requires_booking:
            step_bookings = TeamBooking.objects.filter(work_item=work_item, workflow_step=current_step)
            # Require at least one booking AND all must be completed
            if not step_bookings.exists():
                msg = 'This step requires a booking. Create and complete a booking before moving forward.'
                # Audit trail via system comment
                WorkItemComment.objects.create(
                    work_item=work_item,
                    content=f"Transition blocked: {msg}",
                    author=profile,
                    is_system_comment=True
                )
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': msg, 'requires_booking': True})
                messages.error(request, msg)
                return redirect('cflows:work_item_detail', work_item_id=work_item.id)
            incomplete = step_bookings.filter(is_completed=False).exists()
            if incomplete:
                remaining = step_bookings.filter(is_completed=False).count()
                total = step_bookings.count()
                msg = f'All bookings for this step must be completed before progressing. ({total - remaining}/{total} done)'
                WorkItemComment.objects.create(
                    work_item=work_item,
                    content=f"Transition blocked: {msg}",
                    author=profile,
                    is_system_comment=True
                )
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': msg, 'requires_booking': True})
                messages.error(request, msg)
                return redirect('cflows:work_item_detail', work_item_id=work_item.id)

        with transaction.atomic():
            # Store previous step for history
            from_step = work_item.current_step
            
            # Update work item
            work_item.current_step = transition.to_step
            work_item.current_step_entered_at = timezone.now()
            
            # If transition requires assignment and no assignee, try to auto-assign
            if transition.to_step.assigned_team and not work_item.current_assignee:
                # Auto-assign to first available team member
                team_members = transition.to_step.assigned_team.members.filter(
                    user__is_active=True
                ).first()
                if team_members:
                    work_item.current_assignee = team_members
            
            work_item.save()
            
            # Create history entry
            history = WorkItemHistory.objects.create(
                work_item=work_item,
                from_step=from_step,
                to_step=transition.to_step,
                changed_by=profile,
                notes=notes,
                data_snapshot=work_item.data.copy()
            )
            
            # Add system comment
            WorkItemComment.objects.create(
                work_item=work_item,
                content=f"Moved from '{from_step.name}' to '{transition.to_step.name}'" + (f": {notes}" if notes else ""),
                author=profile,
                is_system_comment=True
            )
            
            # Check if the destination step requires booking
            if transition.to_step.requires_booking and transition.to_step.assigned_team:
                # Redirect to booking creation instead of auto-creating
                messages.success(request, f'Work item moved to "{transition.to_step.name}". Please schedule the required booking.')
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'new_step': transition.to_step.name,
                        'requires_booking': True,
                        'redirect_url': reverse('cflows:create_booking_for_work_item', args=[work_item.id, transition.to_step.id]),
                        'message': f'Moved to {transition.to_step.name}. Booking required.'
                    })
                else:
                    return redirect('cflows:create_booking_for_work_item', work_item_id=work_item.id, step_id=transition.to_step.id)
            
            # Check if work item is now completed
            if transition.to_step.is_terminal:
                work_item.is_completed = True
                work_item.completed_at = timezone.now()
                work_item.save()
                messages.success(request, f'Work item "{work_item.title}" has been completed!')
            else:
                messages.success(request, f'Work item moved to "{transition.to_step.name}"')
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'new_step': transition.to_step.name,
                    'is_completed': work_item.is_completed,
                    'message': f'Moved to {transition.to_step.name}'
                })
            else:
                return redirect('cflows:work_item_detail', work_item_id=work_item.id)
                
    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)})
        else:
            messages.error(request, f'Error moving work item: {str(e)}')
            return redirect('cflows:work_item_detail', work_item_id=work_item.id)


@login_required
@require_organization_access
@require_permission('workitem.transition')
def transition_form(request, work_item_id, transition_id):
    """Show transition confirmation form"""
    profile = get_user_profile(request)
    if not profile:
        messages.error(request, 'No user profile found')
        return redirect('cflows:work_items_list')
    
    work_item = get_object_or_404(
        WorkItem.objects.select_related('workflow', 'current_step'),
        id=work_item_id,
        workflow__organization=profile.organization
    )
    
    transition = get_object_or_404(
        WorkflowTransition.objects.select_related('from_step', 'to_step'),
        id=transition_id,
        from_step=work_item.current_step
    )
    
    context = {
        'profile': profile,
        'work_item': work_item,
        'transition': transition,
    }
    
    return render(request, 'cflows/transition_form.html', context)


@login_required
@require_organization_access
@require_permission('workitem.assign')
@require_POST
def assign_work_item(request, work_item_id):
    """Assign work item to a user"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'success': False, 'error': 'No user profile found'})
    
    work_item = get_object_or_404(
        WorkItem.objects.select_related('workflow', 'current_step'),
        id=work_item_id,
        workflow__organization=profile.organization
    )
    
    assignee_id = request.POST.get('assignee_id')
    if assignee_id:
        try:
            assignee = UserProfile.objects.get(
                id=assignee_id,
                organization=profile.organization,
                user__is_active=True
            )
            
            old_assignee = work_item.current_assignee
            work_item.current_assignee = assignee
            work_item.save()
            
            # Create history entry
            WorkItemHistory.objects.create(
                work_item=work_item,
                from_step=work_item.current_step,
                to_step=work_item.current_step,
                changed_by=profile,
                notes=f"Assigned to {assignee.user.get_full_name() or assignee.user.username}",
                data_snapshot=work_item.data.copy()
            )
            
            # Add system comment
            old_name = old_assignee.user.get_full_name() or old_assignee.user.username if old_assignee else "Unassigned"
            new_name = assignee.user.get_full_name() or assignee.user.username
            WorkItemComment.objects.create(
                work_item=work_item,
                content=f"Assignment changed from {old_name} to {new_name}",
                author=profile,
                is_system_comment=True
            )
            
            messages.success(request, f'Work item assigned to {new_name}')
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'assignee_name': new_name,
                    'message': f'Assigned to {new_name}'
                })
            else:
                return redirect('cflows:work_item_detail', work_item_id=work_item.id)
                
        except UserProfile.DoesNotExist:
            error_msg = 'Invalid assignee selected'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            else:
                messages.error(request, error_msg)
                return redirect('cflows:work_item_detail', work_item_id=work_item.id)
    else:
        # Unassign work item
        old_assignee = work_item.current_assignee
        work_item.current_assignee = None
        work_item.save()
        
        if old_assignee:
            # Create history entry
            WorkItemHistory.objects.create(
                work_item=work_item,
                from_step=work_item.current_step,
                to_step=work_item.current_step,
                changed_by=profile,
                notes="Work item unassigned",
                data_snapshot=work_item.data.copy()
            )
            
            # Add system comment
            old_name = old_assignee.user.get_full_name() or old_assignee.user.username
            WorkItemComment.objects.create(
                work_item=work_item,
                content=f"Unassigned from {old_name}",
                author=profile,
                is_system_comment=True
            )
        
        messages.success(request, 'Work item unassigned')
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'assignee_name': 'Unassigned',
                'message': 'Work item unassigned'
            })
        else:
            return redirect('cflows:work_item_detail', work_item_id=work_item.id)


@login_required
@require_organization_access
@require_permission('workitem.edit')
@require_POST
def update_work_item_priority(request, work_item_id):
    """Update work item priority"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'success': False, 'error': 'No user profile found'})
    
    work_item = get_object_or_404(
        WorkItem,
        id=work_item_id,
        workflow__organization=profile.organization
    )
    
    new_priority = request.POST.get('priority')
    if new_priority in ['low', 'normal', 'high', 'critical']:
        old_priority = work_item.priority
        work_item.priority = new_priority
        work_item.save()
        
        # Create history entry
        WorkItemHistory.objects.create(
            work_item=work_item,
            from_step=work_item.current_step,
            to_step=work_item.current_step,
            changed_by=profile,
            notes=f"Priority changed from {old_priority} to {new_priority}",
            data_snapshot=work_item.data.copy()
        )
        
        # Add system comment
        WorkItemComment.objects.create(
            work_item=work_item,
            content=f"Priority changed from {old_priority.title()} to {new_priority.title()}",
            author=profile,
            is_system_comment=True
        )
        
        messages.success(request, f'Priority updated to {new_priority.title()}')
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'new_priority': new_priority,
                'message': f'Priority updated to {new_priority.title()}'
            })
        else:
            return redirect('cflows:work_item_detail', work_item_id=work_item.id)
    else:
        error_msg = 'Invalid priority value'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': error_msg})
        else:
            messages.error(request, error_msg)
            return redirect('cflows:work_item_detail', work_item_id=work_item.id)


@login_required
@require_organization_access
@require_permission('workitem.transition')
def get_available_transitions(request, work_item_id):
    """Get available transitions for a work item (AJAX endpoint)"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'success': False, 'error': 'No user profile found'})
    
    work_item = get_object_or_404(
        WorkItem.objects.select_related('current_step'),
        id=work_item_id,
        workflow__organization=profile.organization
    )
    
    transitions = work_item.current_step.outgoing_transitions.select_related('to_step').all()
    
    transitions_data = []
    for transition in transitions:
        transitions_data.append({
            'id': transition.id,
            'label': transition.label or f"Move to {transition.to_step.name}",
            'to_step_name': transition.to_step.name,
            'requires_booking': transition.to_step.requires_booking,
            'is_terminal': transition.to_step.is_terminal,
        })
    
    return JsonResponse({
        'success': True,
        'transitions': transitions_data,
        'current_step': work_item.current_step.name
    })


@login_required
@require_organization_access
@require_permission('workitem.transition')
def backward_transition_form(request, work_item_id, step_id):
    """Show form for moving work item backward to a previous step"""
    profile = get_user_profile(request)
    if not profile:
        messages.error(request, 'No user profile found')
        return redirect('cflows:work_items_list')
    
    work_item = get_object_or_404(
        WorkItem.objects.select_related('workflow', 'current_step'),
        id=work_item_id,
        workflow__organization=profile.organization
    )
    
    # Check if user can move items backward
    if not work_item.can_move_backward(profile):
        messages.error(request, 'You do not have permission to move work items backward.')
        return redirect('cflows:work_item_detail', work_item_id=work_item.id)
    
    # Get the target step
    target_step = get_object_or_404(
        WorkflowStep.objects.select_related('assigned_team'),
        id=step_id,
        workflow=work_item.workflow
    )
    
    # Verify this step is in the work item's history
    if not work_item.history.filter(from_step=target_step).exists():
        messages.error(request, 'Cannot move to a step that was not previously visited.')
        return redirect('cflows:work_item_detail', work_item_id=work_item.id)
    
    if request.method == 'POST':
        notes = request.POST.get('notes', '')
        if not notes:
            messages.error(request, 'A comment explaining the backward movement is required.')
        else:
            try:
                with transaction.atomic():
                    # Store previous step for history
                    from_step = work_item.current_step
                    
                    # Update work item
                    work_item.current_step = target_step
                    work_item.current_step_entered_at = timezone.now()
                    
                    # Reset completion status if moving back from terminal step
                    if work_item.is_completed:
                        work_item.is_completed = False
                        work_item.completed_at = None
                    
                    work_item.save()
                    
                    # Create history entry
                    WorkItemHistory.objects.create(
                        work_item=work_item,
                        from_step=from_step,
                        to_step=target_step,
                        changed_by=profile,
                        notes=notes,
                        data_snapshot=work_item.data.copy()
                    )
                    
                    # Add system comment
                    WorkItemComment.objects.create(
                        work_item=work_item,
                        content=f"Moved back from '{from_step.name}' to '{target_step.name}': {notes}",
                        author=profile,
                        is_system_comment=True
                    )
                    
                    # REMOVE FUTURE (DOWNSTREAM) UNCOMPLETED BOOKINGS WHEN MOVING BACK
                    removed_count = 0
                    future_bookings = TeamBooking.objects.filter(
                        work_item=work_item,
                        workflow_step__order__gt=target_step.order,
                        is_completed=False
                    )
                    # Delete (signals will clean scheduling mirror)
                    removed_ids = []
                    for b in future_bookings:
                        removed_ids.append(b.id)
                        b.delete()
                        removed_count += 1

                    if removed_count:
                        # Audit system comment
                        WorkItemComment.objects.create(
                            work_item=work_item,
                            content=f"Removed {removed_count} downstream uncompleted booking(s) on backward move. IDs: {removed_ids}",
                            author=profile,
                            is_system_comment=True
                        )

                    if removed_count:
                        messages.info(request, f'Removed {removed_count} pending booking(s) from later steps.')

                    messages.success(request, f'Work item moved back to "{target_step.name}"')
                    return redirect('cflows:work_item_detail', work_item_id=work_item.id)
                    
            except Exception as e:
                messages.error(request, f'Error moving work item backward: {str(e)}')
    
    context = {
        'work_item': work_item,
        'target_step': target_step,
        'current_step': work_item.current_step,
    }
    
    return render(request, 'cflows/backward_transition_form.html', context)


@login_required
@require_organization_access
@require_permission('workitem.transition')
@require_POST
def move_work_item_back(request, work_item_id, step_id):
    """Move a work item back to a previous step"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'success': False, 'error': 'No user profile found'})
    
    work_item = get_object_or_404(
        WorkItem.objects.select_related('workflow', 'current_step'),
        id=work_item_id,
        workflow__organization=profile.organization
    )
    
    # Check if user can move items backward
    if not work_item.can_move_backward(profile):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Permission denied'})
        else:
            messages.error(request, 'You do not have permission to move work items backward.')
            return redirect('cflows:work_item_detail', work_item_id=work_item.id)
    
    # Get the target step
    target_step = get_object_or_404(
        WorkflowStep.objects.select_related('assigned_team'),
        id=step_id,
        workflow=work_item.workflow
    )
    
    # Verify this step is in the work item's history
    if not work_item.history.filter(from_step=target_step).exists():
        error_msg = 'Cannot move to a step that was not previously visited.'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': error_msg})
        else:
            messages.error(request, error_msg)
            return redirect('cflows:work_item_detail', work_item_id=work_item.id)
    
    notes = request.POST.get('notes', '')
    if not notes:
        error_msg = 'A comment explaining the backward movement is required.'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': error_msg})
        else:
            messages.error(request, error_msg)
            return redirect('cflows:work_item_detail', work_item_id=work_item.id)
    
    try:
        with transaction.atomic():
            # Store previous step for history
            from_step = work_item.current_step
            
            # Update work item
            work_item.current_step = target_step
            work_item.current_step_entered_at = timezone.now()
            
            # Reset completion status if moving back from terminal step
            if work_item.is_completed:
                work_item.is_completed = False
                work_item.completed_at = None
            
            work_item.save()            # Create history entry
            WorkItemHistory.objects.create(
                work_item=work_item,
                from_step=from_step,
                to_step=target_step,
                changed_by=profile,
                notes=notes,
                data_snapshot=work_item.data.copy()
            )
            
            # Add system comment
            WorkItemComment.objects.create(
                work_item=work_item,
                content=f"Moved back from '{from_step.name}' to '{target_step.name}': {notes}",
                author=profile,
                is_system_comment=True
            )
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'new_step': target_step.name,
                    'is_completed': work_item.is_completed,
                    'message': f'Moved back to {target_step.name}'
                })
            else:
                messages.success(request, f'Work item moved back to "{target_step.name}"')
                return redirect('cflows:work_item_detail', work_item_id=work_item.id)
                
    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)})
        else:
            messages.error(request, f'Error moving work item backward: {str(e)}')
            return redirect('cflows:work_item_detail', work_item_id=work_item.id)
