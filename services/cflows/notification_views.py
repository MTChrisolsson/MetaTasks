from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from datetime import datetime, timedelta
from django.db import transaction
import json

from core.models import UserProfile
from .models import WorkItem, WorkflowTransition, TeamBooking


@login_required
def real_time_notifications(request):
    """WebSocket-style long polling for real-time notifications"""
    try:
        user_profile = request.user.mediap_profile
    except UserProfile.DoesNotExist:
        user_profile = None
        
    if not user_profile:
        return JsonResponse({
            'notifications': [],
            'count': 0,
            'timestamp': timezone.now().isoformat()
        })
        
    user_org = user_profile.organization
    last_check = request.GET.get('last_check')
    
    if last_check:
        try:
            # Handle different ISO format variations
            if last_check.endswith('Z'):
                last_check = last_check.replace('Z', '+00:00')
            elif '+' in last_check and last_check.count('+') == 1:
                # Format like: 2025-09-07T18:40:03.157053+00:00
                pass  # Already correct
            elif ' ' in last_check:
                # Format like: 2025-09-07T18:40:03.157053 00:00
                last_check = last_check.replace(' ', '+')
            
            last_check = datetime.fromisoformat(last_check)
        except ValueError:
            # Fallback if parsing fails
            last_check = timezone.now() - timedelta(hours=1)
    else:
        last_check = timezone.now() - timedelta(hours=1)
    
    notifications = []
    
    # Check for new work item assignments - use updated_at and check history
    new_assignments = WorkItem.objects.filter(
        workflow__organization=user_org,
        current_assignee=user_profile,
        updated_at__gt=last_check
    ).select_related('workflow', 'current_step')
    
    # Filter to only items where assignee actually changed recently
    actual_assignments = []
    for item in new_assignments:
        # Check if this is a recent assignment by looking at history
        recent_history = item.history.filter(
            created_at__gt=last_check
        ).order_by('-created_at').first()
        
        # If there's recent history or item was created recently, consider it a new assignment
        if recent_history or item.created_at > last_check:
            actual_assignments.append(item)
    
    for item in actual_assignments:
        notifications.append({
            'type': 'work_item_assigned',
            'title': 'New Work Item Assigned',
            'message': f'You have been assigned to "{item.title}"',
            'url': f'/services/cflows/work-items/{item.id}/',
            'timestamp': item.updated_at.isoformat(),
            'priority': item.priority,
            'workflow': item.workflow.name
        })
    
    # Check for work item transitions affecting user's items
    transitions = WorkItem.objects.filter(
        workflow__organization=user_org,
        current_assignee=user_profile,
        updated_at__gt=last_check
    ).exclude(
        id__in=[item.id for item in actual_assignments]  # Exclude already counted assignments
    ).select_related('workflow', 'current_step')
    
    for item in transitions:
        notifications.append({
            'type': 'work_item_updated',
            'title': 'Work Item Updated',
            'message': f'"{item.title}" has been updated',
            'url': f'/services/cflows/work-items/{item.id}/',
            'timestamp': item.updated_at.isoformat(),
            'priority': item.priority,
            'workflow': item.workflow.name
        })
    
    # Check for upcoming booking deadlines
    upcoming_bookings = TeamBooking.objects.filter(
        assigned_members=user_profile,
        start_time__gte=timezone.now(),
        start_time__lte=timezone.now() + timedelta(days=1),
        is_completed=False
    ).select_related('work_item', 'team')
    
    for booking in upcoming_bookings:
        notifications.append({
            'type': 'booking_reminder',
            'title': 'Booking Reminder',
            'message': f'"{booking.title}" with {booking.team.name} starts {"today" if booking.start_time.date() == timezone.now().date() else "tomorrow"}',
            'url': f'/services/cflows/work-items/{booking.work_item.id}/' if booking.work_item else f'/services/cflows/bookings/{booking.id}/',
            'timestamp': booking.start_time.isoformat(),
            'priority': booking.work_item.priority if booking.work_item else 'normal',
            'team': booking.team.name
        })
    
    # Sort notifications by timestamp (newest first)
    notifications.sort(key=lambda x: x['timestamp'], reverse=True)
    
    return JsonResponse({
        'notifications': notifications,
        'count': len(notifications),
        'timestamp': timezone.now().isoformat()
    })


@login_required
@require_POST
def mark_notification_read(request):
    """Mark notifications as read (placeholder for future notification tracking)"""
    try:
        data = json.loads(request.body)
        notification_ids = data.get('notification_ids', [])
        
        # In a full implementation, you'd mark these notifications as read in the database
        # For now, we'll just return success
        
        return JsonResponse({
            'success': True,
            'message': f'Marked {len(notification_ids)} notifications as read'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


def get_dashboard_stats(user_profile):
    """Get dashboard statistics for the user"""
    stats = {}
    
    # Work items assigned to user
    my_items = WorkItem.objects.filter(
        workflow__organization=user_profile.organization,
        current_assignee=user_profile,
        is_completed=False
    )
    
    stats['my_active_items'] = my_items.count()
    stats['my_high_priority'] = my_items.filter(priority__in=['high', 'critical']).count()
    
    # Team bookings
    my_bookings = TeamBooking.objects.filter(
        assigned_members=user_profile,
        start_time__gte=timezone.now(),
        is_completed=False
    )
    
    stats['my_upcoming_bookings'] = my_bookings.count()
    stats['my_today_bookings'] = my_bookings.filter(
        start_time__date=timezone.now().date()
    ).count()
    
    # Organization totals (for admin users)
    if user_profile.role in ['admin', 'manager']:
        org_items = WorkItem.objects.filter(
            workflow__organization=user_profile.organization
        )
        
        stats['org_total_items'] = org_items.count()
        stats['org_active_items'] = org_items.filter(is_completed=False).count()
        stats['org_overdue_items'] = org_items.filter(
            due_date__lt=timezone.now().date(),
            is_completed=False
        ).count()
    
    return stats
