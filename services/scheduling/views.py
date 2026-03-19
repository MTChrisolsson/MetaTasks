from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from datetime import datetime, timedelta, date, time
from core.views import require_organization_access
from core.models import UserProfile
from .models import SchedulableResource, BookingRequest, ResourceScheduleRule
from .services import SchedulingService, ResourceManagementService
from .integrations import get_service_integration
from .forms import BookingForm, ResourceForm
from .workflow_integration import BookingWorkflowIntegration
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
def index(request):
    """Enhanced scheduling service dashboard"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'scheduling/no_profile.html')
    
    # Get today's and comparison dates
    today = timezone.now().date()
    yesterday = today - timedelta(days=1)
    next_week = today + timedelta(days=7)
    
    # Today's bookings with detailed statuses
    today_bookings = BookingRequest.objects.filter(
        organization=profile.organization,
        requested_start__date=today
    ).select_related('resource', 'requested_by', 'completed_by').order_by('requested_start')
    
    # Yesterday's bookings for comparison
    yesterday_bookings = BookingRequest.objects.filter(
        organization=profile.organization,
        requested_start__date=yesterday
    ).count()
    
    # Get active resources with utilization info
    resources = list(SchedulableResource.objects.filter(
        organization=profile.organization,
        is_active=True
    ).select_related('linked_team').annotate(
        today_booking_count=Count(
            'bookingrequest',
            filter=Q(
                bookingrequest__requested_start__date=today,
                bookingrequest__status__in=['confirmed', 'in_progress', 'completed']
            )
        )
    ))
    
    # Calculate resource utilization for today
    resource_utilization = []
    for resource in resources:
        today_usage = resource.today_booking_count
        
        total_capacity = resource.max_concurrent_bookings
        utilization_percent = (today_usage / total_capacity * 100) if total_capacity > 0 else 0
        
        resource_utilization.append({
            'resource': resource,
            'today_bookings': today_usage,
            'capacity': total_capacity,
            'utilization_percent': round(utilization_percent, 1)
        })
    
    # Get upcoming bookings (next 7 days)
    upcoming_bookings = BookingRequest.objects.filter(
        organization=profile.organization,
        requested_start__date__gt=today,
        requested_start__date__lte=next_week,
        status__in=['pending', 'confirmed']
    ).select_related('resource', 'requested_by').order_by('requested_start')[:10]
    
    # Get pending requests with urgency
    pending_requests_qs = BookingRequest.objects.filter(
        organization=profile.organization,
        status='pending'
    ).select_related('resource', 'requested_by').order_by('created_at')
    pending_requests = pending_requests_qs[:5]
    
    # Recent activity (last 7 days)
    recent_activity = BookingRequest.objects.filter(
        organization=profile.organization,
        created_at__gte=timezone.now() - timedelta(days=7)
    ).select_related('resource', 'requested_by').order_by('-created_at')[:10]
    
    # Today's schedule timeline
    todays_schedule = today_bookings.filter(
        status__in=['confirmed', 'in_progress']
    ).order_by('requested_start')
    
    # Calculate trends
    today_booking_stats = today_bookings.aggregate(
        total=Count('id'),
        active=Count('id', filter=Q(status='in_progress')),
        completed=Count('id', filter=Q(status='completed')),
    )
    total_bookings_today = today_booking_stats['total']
    active_bookings = today_booking_stats['active']
    completed_today = today_booking_stats['completed']
    pending_count = pending_requests_qs.count()
    
    # Calculate percentage changes
    booking_trend = ((total_bookings_today - yesterday_bookings) / yesterday_bookings * 100) if yesterday_bookings > 0 else 0
    
    # Overdue bookings (should have been completed but are still in progress)
    now = timezone.now()
    overdue_bookings = BookingRequest.objects.filter(
        organization=profile.organization,
        status='in_progress',
        requested_end__lt=now
    ).select_related('resource', 'requested_by')
    
    # Next 3 hours schedule
    next_3_hours = now + timedelta(hours=3)
    immediate_schedule = BookingRequest.objects.filter(
        organization=profile.organization,
        requested_start__gte=now,
        requested_start__lte=next_3_hours,
        status__in=['confirmed', 'pending']
    ).select_related('resource', 'requested_by').order_by('requested_start')
    
    context = {
        'profile': profile,
        'page_title': 'Scheduling Dashboard',
        'resources': resources,
        'today_bookings': today_bookings,
        'upcoming_bookings': upcoming_bookings,
        'pending_requests': pending_requests,
        'recent_activity': recent_activity,
        'todays_schedule': todays_schedule,
        'resource_utilization': resource_utilization,
        'overdue_bookings': overdue_bookings,
        'immediate_schedule': immediate_schedule,
        'stats': {
            'total_bookings_today': total_bookings_today,
            'active_bookings': active_bookings,
            'completed_bookings': completed_today,
            'pending_requests_count': pending_count,
            'total_resources': len(resources),
            'overdue_count': overdue_bookings.count(),
            'booking_trend': round(booking_trend, 1),
            'resource_utilization_avg': round(
                sum([ru['utilization_percent'] for ru in resource_utilization]) / len(resource_utilization), 1
            ) if resource_utilization else 0
        }
    }
    
    return render(request, 'scheduling/dashboard.html', context)


@login_required
@require_organization_access
def calendar_view(request):
    """Main calendar interface"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'scheduling/no_profile.html')
    
    # Get resources for filter
    resources = SchedulableResource.objects.filter(
        organization=profile.organization,
        is_active=True
    ).select_related('linked_team')
    
    context = {
        'profile': profile,
        'page_title': 'Calendar',
        'resources': resources,
    }
    
    return render(request, 'scheduling/calendar.html', context)


@login_required
@require_organization_access  
def resource_list(request):
    """List all schedulable resources"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'scheduling/no_profile.html')
    
    resources = SchedulableResource.objects.filter(
        organization=profile.organization
    ).select_related('linked_team').order_by('name')
    
    # Add pagination
    paginator = Paginator(resources, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'profile': profile,
        'page_title': 'Resources',
        'page_obj': page_obj,
        'resources': page_obj,
    }
    
    return render(request, 'scheduling/resource_list.html', context)


@login_required
@require_organization_access
def resource_detail(request, resource_id):
    """Detailed view of resource capacity and bookings"""
    profile = get_user_profile(request)
    
    resource = get_object_or_404(
        SchedulableResource,
        id=resource_id,
        organization=profile.organization
    )
    
    # Get date range from request
    start_date = request.GET.get('start_date')
    if start_date:
        try:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        except ValueError:
            start_date = timezone.now().date()
    else:
        start_date = timezone.now().date()
    
    end_date = start_date + timedelta(days=14)  # Two weeks view
    
    scheduling_service = SchedulingService(profile.organization)
    availability_data = scheduling_service.get_resource_availability(
        resource, start_date, end_date
    )
    
    # Get utilization stats
    stats = scheduling_service.get_resource_utilization_stats(
        resource, start_date, end_date
    )
    
    # Get recent bookings
    recent_bookings = BookingRequest.objects.filter(
        resource=resource,
        requested_start__gte=start_date - timedelta(days=7)
    ).select_related('requested_by', 'completed_by').order_by('-created_at')[:10]
    
    context = {
        'profile': profile,
        'resource': resource,
        'availability_data': availability_data,
        'utilization_stats': stats,
        'recent_bookings': recent_bookings,
        'start_date': start_date,
        'end_date': end_date,
        'page_title': f'Resource: {resource.name}',
    }
    
    return render(request, 'scheduling/resource_detail.html', context)


@login_required
@require_organization_access
def booking_list(request):
    """List all bookings"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'scheduling/no_profile.html')
    
    # Filter parameters
    status = request.GET.get('status', '')
    resource_id = request.GET.get('resource', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    bookings = BookingRequest.objects.filter(
        organization=profile.organization
    ).select_related('resource', 'requested_by', 'completed_by')
    
    # Apply filters
    if status:
        bookings = bookings.filter(status=status)
    if resource_id:
        bookings = bookings.filter(resource_id=resource_id)
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            bookings = bookings.filter(requested_start__date__gte=date_from_obj)
        except ValueError:
            pass
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            bookings = bookings.filter(requested_start__date__lte=date_to_obj)
        except ValueError:
            pass
    
    bookings = bookings.order_by('-created_at')
    
    # Pagination
    paginator = Paginator(bookings, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get resources for filter dropdown
    resources = SchedulableResource.objects.filter(
        organization=profile.organization,
        is_active=True
    ).order_by('name')
    
    context = {
        'profile': profile,
        'page_title': 'Bookings',
        'page_obj': page_obj,
        'bookings': page_obj,
        'resources': resources,
        'current_filters': {
            'status': status,
            'resource': resource_id,
            'date_from': date_from,
            'date_to': date_to,
        },
        'status_choices': BookingRequest.STATUS_CHOICES,
    }
    
    return render(request, 'scheduling/booking_list.html', context)


@login_required
@require_organization_access
def booking_detail(request, booking_id):
    """Detailed view of a booking"""
    profile = get_user_profile(request)
    
    booking = get_object_or_404(
        BookingRequest,
        id=booking_id,
        organization=profile.organization
    )
    
    context = {
        'profile': profile,
        'booking': booking,
        'page_title': f'Booking: {booking.title}',
    }
    
    return render(request, 'scheduling/booking_detail.html', context)


@login_required
@require_organization_access
@require_http_methods(["POST"])
def booking_action(request, booking_id, action):
    """Handle booking actions (confirm, start, complete, cancel)"""
    profile = get_user_profile(request)
    
    booking = get_object_or_404(
        BookingRequest,
        id=booking_id,
        organization=profile.organization
    )
    
    scheduling_service = SchedulingService(profile.organization)
    success = False
    
    if action == 'confirm':
        success = scheduling_service.confirm_booking(booking, profile)
        message = "Booking confirmed successfully" if success else "Failed to confirm booking"
    elif action == 'start':
        success = scheduling_service.start_booking(booking, profile)
        message = "Booking started successfully" if success else "Failed to start booking"
    elif action == 'complete':
        success = scheduling_service.complete_booking(booking, profile)
        message = "Booking completed successfully" if success else "Failed to complete booking"
    elif action == 'cancel':
        reason = request.POST.get('reason', '')
        success = scheduling_service.cancel_booking(booking, reason)
        message = "Booking cancelled successfully" if success else "Failed to cancel booking"
    else:
        message = "Invalid action"
    
    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)
    
    return redirect('scheduling:booking_detail', booking_id=booking.id)


@login_required
@require_organization_access
def create_booking(request):
    """Create a new booking"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'scheduling/no_profile.html')
    
    if request.method == 'POST':
        form = BookingForm(request.POST, organization=profile.organization)
        if form.is_valid():
            try:
                scheduling_service = SchedulingService(profile.organization)
                
                booking = scheduling_service.create_booking(
                    user_profile=profile,
                    resource=form.cleaned_data['resource'],
                    start_time=form.cleaned_data['requested_start'],
                    end_time=form.cleaned_data['requested_end'],
                    title=form.cleaned_data['title'],
                    description=form.cleaned_data['description'],
                    priority=form.cleaned_data['priority']
                )
                
                messages.success(request, f'Booking "{booking.title}" created successfully!')
                return redirect('scheduling:booking_detail', booking_id=booking.id)
                
            except Exception as e:
                messages.error(request, f'Failed to create booking: {str(e)}')
    else:
        form = BookingForm(organization=profile.organization)
    
    context = {
        'profile': profile,
        'form': form,
        'page_title': 'Create New Booking',
    }
    
    return render(request, 'scheduling/create_booking.html', context)


@login_required
@require_organization_access
def create_resource(request):
    """Create a new resource"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'scheduling/no_profile.html')
    
    if request.method == 'POST':
        form = ResourceForm(request.POST)
        if form.is_valid():
            try:
                resource = form.save(commit=False)
                resource.organization = profile.organization
                resource.save()
                
                messages.success(request, f'Resource "{resource.name}" created successfully!')
                return redirect('scheduling:resource_detail', resource_id=resource.id)
                
            except Exception as e:
                messages.error(request, f'Failed to create resource: {str(e)}')
    else:
        form = ResourceForm()
    
    context = {
        'profile': profile,
        'form': form,
        'page_title': 'Create New Resource',
    }
    
    return render(request, 'scheduling/create_resource.html', context)


@login_required  
@require_organization_access
def api_calendar_events(request):
    """API endpoint for calendar events"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'error': 'No profile found'}, status=400)
    
    # Get date range - provide defaults if not specified
    start = request.GET.get('start')
    end = request.GET.get('end')
    resource_ids = request.GET.getlist('resources[]')
    
    # Default to current month if no dates provided
    if not start or not end:
        today = timezone.now().date()
        start_dt = timezone.make_aware(datetime.combine(today.replace(day=1), time.min))
        end_dt = timezone.make_aware(datetime.combine(
            (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1), 
            time.max
        ))
    else:
        try:
            start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
        except ValueError:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
    
    # Build query
    bookings = BookingRequest.objects.filter(
        organization=profile.organization,
        requested_start__lt=end_dt,
        requested_end__gt=start_dt
    ).select_related('resource', 'requested_by')
    
    if resource_ids:
        bookings = bookings.filter(resource_id__in=resource_ids)
    
    # Format events for calendar
    events = []
    for booking in bookings:
        color_map = {
            'confirmed': '#3b82f6',
            'in_progress': '#10b981', 
            'completed': '#6b7280',
            'pending': '#f59e0b'
        }
        color = color_map.get(booking.status, '#3b82f6')
        
        events.append({
            'id': booking.id,
            'uuid': str(booking.uuid),
            'title': booking.title,
            'start': booking.requested_start.isoformat(),
            'end': booking.requested_end.isoformat(),
            'status': booking.status,
            'resource': booking.resource.name if booking.resource else None,
            'resourceType': booking.resource.get_resource_type_display() if booking.resource else None,
            'description': booking.description,
            'requestedBy': booking.requested_by.user.get_full_name() if booking.requested_by and booking.requested_by.user else None,
            'sourceService': booking.source_service,
            'backgroundColor': color,
            'borderColor': color
        })
    
    return JsonResponse(events, safe=False)


@login_required
@require_organization_access
def api_check_availability(request):
    """API endpoint for checking resource availability"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'error': 'No profile found'}, status=400)
    
    resource_id = request.GET.get('resource_id')
    start_time = request.GET.get('start_time')
    end_time = request.GET.get('end_time')
    
    if not all([resource_id, start_time, end_time]):
        return JsonResponse({'error': 'Missing required parameters'}, status=400)
    
    try:
        resource = SchedulableResource.objects.get(
            id=resource_id,
            organization=profile.organization
        )
        
        start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        
        scheduling_service = SchedulingService(profile.organization)
        is_available = scheduling_service.is_time_slot_available(resource, start_dt, end_dt)
        
        response_data = {
            'available': is_available,
            'resource_name': resource.name,
            'requested_time': {
                'start': start_dt.isoformat(),
                'end': end_dt.isoformat()
            }
        }
        
        if not is_available:
            # Get suggestions for alternative times
            duration = end_dt - start_dt
            suggestions = scheduling_service.suggest_alternative_times(
                resource, start_dt, duration, max_alternatives=5
            )
            response_data['suggestions'] = suggestions
        
        return JsonResponse(response_data)
        
    except SchedulableResource.DoesNotExist:
        return JsonResponse({'error': 'Resource not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_organization_access  
def api_suggest_times(request):
    """API endpoint for suggesting alternative booking times"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'error': 'No profile found'}, status=400)
    
    resource_id = request.GET.get('resource_id')
    preferred_start = request.GET.get('preferred_start')
    duration_hours = request.GET.get('duration_hours', '2')
    
    if not all([resource_id, preferred_start]):
        return JsonResponse({'error': 'Missing required parameters'}, status=400)
    
    try:
        resource = SchedulableResource.objects.get(
            id=resource_id,
            organization=profile.organization
        )
        start_dt = datetime.fromisoformat(preferred_start.replace('Z', '+00:00'))
        duration = timedelta(hours=float(duration_hours))
    except (SchedulableResource.DoesNotExist, ValueError):
        return JsonResponse({'error': 'Invalid resource or date'}, status=400)
    
    scheduling_service = SchedulingService(profile.organization)
    suggestions = scheduling_service.suggest_alternative_times(
        resource, start_dt, duration, max_alternatives=10
    )
    
    return JsonResponse({'suggestions': suggestions})


@login_required
@require_organization_access
def sync_teams(request):
    """Sync all teams to schedulable resources"""
    profile = get_user_profile(request)
    if not profile:
        messages.error(request, 'No profile found')
        return redirect('scheduling:index')
    
    resource_service = ResourceManagementService(profile.organization)
    resources = resource_service.sync_team_resources()
    
    messages.success(request, f'Successfully synced {len(resources)} team resources')
    return redirect('scheduling:resource_list')


@login_required  
@require_organization_access
def sync_cflows_bookings(request):
    """Sync existing CFlows TeamBooking records"""
    profile = get_user_profile(request)
    if not profile:
        messages.error(request, 'No profile found')
        return redirect('scheduling:index')
    
    try:
        from .integrations import CFlowsIntegration
        integration = CFlowsIntegration(profile.organization)
        bookings = integration.sync_all_team_bookings()
        
        messages.success(request, f'Successfully synced {len(bookings)} CFlows bookings')
    except Exception as e:
        messages.error(request, f'Error syncing CFlows bookings: {str(e)}')
    
    return redirect('scheduling:booking_list')


@login_required
@require_organization_access
def resources_list(request):
    """List of available resources with live data"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'scheduling/no_profile.html')
    
    # Get all resources for the organization
    resources = SchedulableResource.objects.filter(
        organization=profile.organization
    ).select_related('linked_team').order_by('name')
    
    # Calculate resource type counts
    resource_counts = {
        'person': resources.filter(resource_type='person').count(),
        'equipment': resources.filter(resource_type='equipment').count(),
        'room': resources.filter(resource_type='room').count(),
        'vehicle': resources.filter(resource_type='vehicle').count(),
        'other': resources.filter(resource_type='other').count(),
    }
    
    # Get current availability data for today
    today = timezone.now().date()
    resource_availability = []
    
    for resource in resources:
        # Get today's bookings for this resource
        today_bookings = BookingRequest.objects.filter(
            resource=resource,
            requested_start__date=today,
            status__in=['confirmed', 'in_progress', 'completed']
        ).count()
        
        utilization = (today_bookings / resource.max_concurrent_bookings * 100) if resource.max_concurrent_bookings > 0 else 0
        
        resource_availability.append({
            'resource': resource,
            'today_bookings': today_bookings,
            'utilization_percent': round(utilization, 1),
            'status': 'busy' if utilization > 80 else 'available' if utilization < 50 else 'moderate'
        })
    
    context = {
        'profile': profile,
        'page_title': 'Resources',
        'resources': resources,
        'resource_counts': resource_counts,
        'resource_availability': resource_availability,
        'total_resources': resources.count(),
        'active_resources': resources.filter(is_active=True).count(),
    }
    
    return render(request, 'scheduling/resources_list.html', context)


@login_required
@require_organization_access
def projects_list(request):
    """List projects"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'scheduling/no_profile.html')
    
    context = {
        'profile': profile,
        'page_title': 'Projects',
    }
    
    return render(request, 'scheduling/projects_list.html', context)


@login_required
@require_organization_access
def create_project(request):
    """Create new project"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'scheduling/no_profile.html')
    
    context = {
        'profile': profile,
        'page_title': 'Create Project',
    }
    
    return render(request, 'scheduling/create_project.html', context)


@login_required
@require_organization_access
def project_detail(request, pk):
    """Project detail view"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'scheduling/no_profile.html')
    
    context = {
        'profile': profile,
        'project_id': pk,
        'page_title': f'Project {pk}',
    }
    
    return render(request, 'scheduling/project_detail.html', context)


@login_required
@require_organization_access
@require_organization_access
def complete_booking_workflow_prompt(request, booking_uuid):
    """Handle both displaying and processing the workflow completion form."""
    booking = get_object_or_404(BookingRequest, uuid=booking_uuid)
    
    # Check if workflow integration is available
    work_item = BookingWorkflowIntegration.get_linked_work_item(booking)
    if not work_item:
        messages.error(request, "No workflow integration found for this booking.")
        return redirect('scheduling:booking_detail', uuid=booking.uuid)
    
    if request.method == 'POST':
        # Handle workflow completion form submission
        profile = get_user_profile(request)
        if not profile:
            return JsonResponse({'error': 'User profile not found'}, status=400)
        
        workflow_action = request.POST.get('workflow_action', 'no_change')
        target_step_id = request.POST.get('target_step_id')
        completion_notes = request.POST.get('completion_notes', '')
        mark_work_item_complete = request.POST.get('mark_work_item_complete') == 'on'
        
        # Complete booking with workflow update
        result = BookingWorkflowIntegration.complete_booking_with_workflow_update(
            booking=booking,
            completed_by=profile,
            workflow_action=workflow_action,
            target_step_id=int(target_step_id) if target_step_id else None,
            completion_notes=completion_notes,
            mark_work_item_complete=mark_work_item_complete
        )
        
        if request.headers.get('Content-Type') == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(result)
        else:
            # Add messages and redirect
            if result.get('success'):
                for message in result.get('messages', []):
                    messages.success(request, message)
                return redirect('scheduling:booking_list')
            else:
                messages.error(request, result.get('error', 'Unknown error occurred'))
                return redirect('scheduling:booking_detail', uuid=booking.uuid)
    
    # GET request - display the form
    completion_options = BookingWorkflowIntegration.get_completion_options(work_item)
    
    if request.headers.get('Content-Type') == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Return prompt data for AJAX requests
        # Extract serializable data from completion_options
        serializable_options = {
            'next_steps': completion_options.get('next_steps', []),
            'backward_steps': completion_options.get('backward_steps', []),
            'can_complete': completion_options.get('can_complete', False),
            'requires_booking': completion_options.get('requires_booking', False)
        }
        
        return JsonResponse({
            'prompt_required': True,
            'booking': {
                'uuid': str(booking.uuid),
                'title': booking.title,
                'description': booking.description,
                'status': booking.status,
            },
            'work_item': {
                'uuid': str(work_item.uuid),
                'title': work_item.title,
                'current_step': work_item.current_step.name if work_item.current_step else None,
            },
            'completion_options': serializable_options
        })
    
    # Regular HTML request - render the form template
    context = {
        'booking': booking,
        'work_item': work_item,
        'completion_options': completion_options,
    }
    
    return render(request, 'scheduling/complete_booking_workflow.html', context)


@login_required
@require_organization_access  
def complete_booking(request, booking_uuid):
    """Complete a booking (with optional workflow integration)"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'error': 'User profile not found'}, status=400)
    
    booking = get_object_or_404(
        BookingRequest, 
        uuid=booking_uuid, 
        organization=profile.organization
    )
    
    if booking.status == 'completed':
        error_msg = 'Booking is already completed'
        if request.headers.get('Content-Type') == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': error_msg}, status=400)
        else:
            messages.error(request, error_msg)
            return redirect('scheduling:booking_detail', booking_id=booking.id)
    
    # Check if we should prompt for workflow action
    should_prompt = BookingWorkflowIntegration.should_prompt_workflow_update(booking)
    
    if should_prompt and request.method == 'GET':
        # Return prompt requirement instead of completing directly
        if request.headers.get('Content-Type') == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'requires_workflow_prompt': True,
                'prompt_url': f'/services/scheduling/bookings/{booking_uuid}/complete-workflow/'
            })
        else:
            # Redirect to workflow prompt page
            return redirect('scheduling:complete_booking_workflow', booking_uuid=booking_uuid)
    
    if request.method == 'POST':
        # Simple completion without workflow integration
        booking.status = 'completed'
        booking.completed_by = profile
        booking.completed_at = timezone.now()
        booking.actual_end = timezone.now()
        
        completion_notes = request.POST.get('completion_notes', '')
        if completion_notes:
            booking.custom_data['completion_notes'] = completion_notes
            booking.custom_data['completed_at'] = booking.completed_at.isoformat()
        
        booking.save()

        # Sync to CFlows if booking originated from CFlows TeamBooking (case-insensitive)
        if (booking.source_service == 'cflows' and 
            booking.source_object_type.lower() in ['teambooking', 'team_booking']):
            from .integrations import get_service_integration
            integration = get_service_integration(booking.organization, 'cflows')
            integration.mark_completed(request, [booking])
        
        messages.success(request, f'Booking "{booking.title}" completed successfully.')
        
        # Check if this is an AJAX request
        if request.headers.get('Content-Type') == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Booking completed successfully',
                'booking_status': booking.status
            })
        else:
            # Regular form submission - redirect to booking detail page
            return redirect('scheduling:booking_detail', booking_id=booking.id)
    
    # GET request for simple completion form
    context = {
        'profile': profile,
        'booking': booking,
    }
    
    return render(request, 'scheduling/complete_booking.html', context)
