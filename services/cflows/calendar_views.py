from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, Http404
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.utils import timezone
from datetime import datetime, timedelta, date
import json

from core.models import Organization, UserProfile, Team, CalendarEvent, JobType
from .models import (
    Workflow, WorkflowStep, WorkItem, TeamBooking
)
from core.views import require_organization_access, require_business_organization


def get_user_profile(request):
    """Safely get user profile"""
    try:
        return request.user.mediap_profile
    except UserProfile.DoesNotExist:
        return None


@login_required
@require_organization_access  
def calendar_view(request):
    """Calendar view with events and bookings"""
    profile = get_user_profile(request)
    
    if not profile:
        return render(request, 'cflows/no_profile.html')
    
    # Get filter options for the organization
    teams = Team.objects.filter(
        organization=profile.organization,
        is_active=True
    ).order_by('name')
    
    job_types = JobType.objects.filter(
        organization=profile.organization,
        is_active=True
    ).order_by('name')
    
    workflows = Workflow.objects.filter(
        organization=profile.organization,
        is_active=True
    ).order_by('name')
    
    # Get current filter values
    current_filters = {
        'teams': request.GET.getlist('team'),
        'job_types': request.GET.getlist('job_type'),
        'workflows': request.GET.getlist('workflow'),
        'event_type': request.GET.get('event_type', ''),
        'status': request.GET.get('status', ''),
        'booked_by': request.GET.get('booked_by', ''),
    }
    
    # Get users for booked_by filter
    users_with_bookings = UserProfile.objects.filter(
        organization=profile.organization,
        user__is_active=True,
        created_cflows_bookings__isnull=False
    ).distinct().select_related('user').order_by('user__first_name', 'user__last_name')
    
    # Get saved calendar views
    from .models import CalendarView
    saved_views = CalendarView.objects.filter(user=profile).order_by('name')

    context = {
        'profile': profile,
        'organization': profile.organization,
        'teams': teams,
        'job_types': job_types,
        'workflows': workflows,
        'users_with_bookings': users_with_bookings,
        'current_filters': current_filters,
        'saved_views': saved_views,
    }
    
    return render(request, 'cflows/calendar.html', context)


@login_required
@require_organization_access
def calendar_events(request):
    """JSON API for calendar events with filtering"""
    profile = get_user_profile(request)
    
    if not profile:
        return JsonResponse({'error': 'No profile found'}, status=403)

    user_org = profile.organization
    
    # Parse date range from FullCalendar
    start_param = request.GET.get('start')
    end_param = request.GET.get('end')
    
    # Get filter parameters
    team_filters = request.GET.getlist('team')
    job_type_filters = request.GET.getlist('job_type')
    workflow_filters = request.GET.getlist('workflow')
    event_type_filter = request.GET.get('event_type', '').strip()
    status_filter = request.GET.get('status', '').strip()
    booked_by_filter = request.GET.get('booked_by', '').strip()
    
    try:
        if start_param:
            start_date = datetime.fromisoformat(start_param.replace('Z', '+00:00')).date()
        else:
            start_date = timezone.now().date() - timedelta(days=30)
            
        if end_param:
            end_date = datetime.fromisoformat(end_param.replace('Z', '+00:00')).date()
        else:
            end_date = timezone.now().date() + timedelta(days=60)
    except ValueError:
        return JsonResponse({'error': 'Invalid date format'}, status=400)

    events = []
    
    try:
        # Get team bookings with filtering
        bookings_query = TeamBooking.objects.filter(
            team__organization=user_org,
            start_time__date__gte=start_date,
            end_time__date__lte=end_date
        ).select_related('team', 'work_item', 'work_item__workflow', 'booked_by', 'job_type')
        
        # Apply team filter
        if team_filters:
            bookings_query = bookings_query.filter(team__id__in=team_filters)
        
        # Apply job type filter
        if job_type_filters:
            bookings_query = bookings_query.filter(job_type__id__in=job_type_filters)
        
        # Apply workflow filter
        if workflow_filters:
            bookings_query = bookings_query.filter(work_item__workflow__id__in=workflow_filters)
        
        # Apply status filter
        if status_filter == 'completed':
            bookings_query = bookings_query.filter(is_completed=True)
        elif status_filter == 'pending':
            bookings_query = bookings_query.filter(is_completed=False)
        
        # Apply booked by filter
        if booked_by_filter:
            bookings_query = bookings_query.filter(booked_by__id=booked_by_filter)
        
        for booking in bookings_query:
            # Determine color based on completion status
            if booking.is_completed:
                bg_color = '#10b981'
                border_color = '#059669'
            elif booking.start_time <= timezone.now():
                bg_color = '#f59e0b'
                border_color = '#d97706'
            else:
                bg_color = '#3b82f6'
                border_color = '#1e40af'
            
            events.append({
                'id': f'booking-{booking.id}',
                'title': f'{booking.title} ({booking.team.name})',
                'start': booking.start_time.isoformat(),
                'end': booking.end_time.isoformat(),
                'backgroundColor': bg_color,
                'borderColor': border_color,
                'extendedProps': {
                    'type': 'booking',
                    'bookingId': booking.id,
                    'workItemId': booking.work_item.id if booking.work_item else None,
                    'teamName': booking.team.name,
                    'bookedBy': booking.booked_by.user.get_full_name() if booking.booked_by and booking.booked_by.user else 'System',
                    'workflow': booking.work_item.workflow.name if booking.work_item else 'Direct Booking',
                    'isCompleted': booking.is_completed,
                    'description': booking.description,
                    'requiredMembers': booking.required_members,
                    'jobType': booking.job_type.name if booking.job_type else None
                }
            })
        
        # Get calendar events with filtering
        calendar_events_query = CalendarEvent.objects.filter(
            organization=user_org,
            start_time__date__gte=start_date,
            end_time__date__lte=end_date,
            is_cancelled=False
        ).select_related('created_by', 'related_team')
        
        # Apply team filter for calendar events
        if team_filters:
            calendar_events_query = calendar_events_query.filter(related_team__id__in=team_filters)
        
        # Apply event type filter
        if event_type_filter:
            calendar_events_query = calendar_events_query.filter(event_type=event_type_filter)
        
        for event in calendar_events_query:
            events.append({
                'id': f'event-{event.id}',
                'title': event.title,
                'start': event.start_time.isoformat(),
                'end': event.end_time.isoformat(),
                'backgroundColor': event.color,
                'borderColor': event.color,
                'allDay': event.is_all_day,
                'extendedProps': {
                    'type': 'event',
                    'eventId': event.id,
                    'description': event.description,
                    'location': event.location,
                    'eventType': event.event_type,
                    'createdBy': event.created_by.user.get_full_name() if event.created_by and event.created_by.user else 'System',
                    'team': event.related_team.name if event.related_team else None,
                    'isAllDay': event.is_all_day
                }
            })
        
        # Get work item due dates
        work_items = WorkItem.objects.filter(
            workflow__organization=user_org,
            due_date__isnull=False,
            due_date__date__gte=start_date,
            due_date__date__lte=end_date,
            is_completed=False
        ).select_related('workflow', 'current_assignee')
        
        for item in work_items:
            # Due date items as all-day events
            events.append({
                'id': f'workitem-{item.id}',
                'title': f'Due: {item.title}',
                'start': item.due_date.date().isoformat(),
                'backgroundColor': '#ef4444',
                'borderColor': '#dc2626',
                'allDay': True,
                'extendedProps': {
                    'type': 'due_date',
                    'workItemId': item.id,
                    'priority': item.priority,
                    'assignee': item.current_assignee.user.get_full_name() if item.current_assignee and item.current_assignee.user else 'Unassigned',
                    'workflow': item.workflow.name
                }
            })
        
    except Exception as e:
        return JsonResponse({'error': f'Error fetching events: {str(e)}'}, status=500)
    
    return JsonResponse(events, safe=False)


@login_required
@require_business_organization
@require_POST
def create_booking(request):
    """Create a new team booking"""
    try:
        profile = get_user_profile(request)
        if not profile:
            return JsonResponse({'success': False, 'error': 'No profile found'})
        
        user_org = profile.organization
        data = json.loads(request.body)
        
        # Validate required fields
        required_fields = ['team_id', 'title', 'start_time', 'end_time']
        for field in required_fields:
            if field not in data:
                return JsonResponse({'success': False, 'error': f'Missing required field: {field}'})
        
        # Get team
        try:
            team = Team.objects.get(id=data['team_id'], organization=user_org)
        except Team.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Team not found'})
        
        # Parse datetime strings
        try:
            start_time = datetime.fromisoformat(data['start_time'].replace('Z', '+00:00'))
            end_time = datetime.fromisoformat(data['end_time'].replace('Z', '+00:00'))
            
            # Convert to local timezone if needed
            if timezone.is_aware(start_time):
                start_time = timezone.localtime(start_time)
                end_time = timezone.localtime(end_time)
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Invalid datetime format'})
        
        # Validate times
        if start_time >= end_time:
            return JsonResponse({'success': False, 'error': 'Start time must be before end time'})
        
        # Check for conflicts
        conflicts = TeamBooking.objects.filter(
            team=team,
            is_completed=False,
            start_time__lt=end_time,
            end_time__gt=start_time
        )
        
        if data.get('booking_id'):  # Exclude current booking if updating
            conflicts = conflicts.exclude(id=data['booking_id'])
        
        if conflicts.exists():
            conflict_list = []
            for conflict in conflicts[:3]:  # Show first 3 conflicts
                conflict_list.append(f"{conflict.title} ({conflict.start_time.strftime('%Y-%m-%d %H:%M')} - {conflict.end_time.strftime('%H:%M')})")
            
            return JsonResponse({
                'success': False, 
                'error': f'Team booking conflicts with: {", ".join(conflict_list)}'
            })
        
        # Optional related objects
        work_item = None
        if data.get('work_item_id'):
            try:
                work_item = WorkItem.objects.get(id=data['work_item_id'], workflow__organization=user_org)
            except WorkItem.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Work item not found'})
        
        workflow_step = None
        if data.get('workflow_step_id'):
            try:
                workflow_step = WorkflowStep.objects.get(id=data['workflow_step_id'])
            except WorkflowStep.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Workflow step not found'})
        
        job_type = None
        if data.get('job_type_id'):
            try:
                job_type = JobType.objects.get(id=data['job_type_id'], organization=user_org)
            except JobType.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Job type not found'})
        
        # Create booking
        with transaction.atomic():
            booking = TeamBooking.objects.create(
                team=team,
                work_item=work_item,
                workflow_step=workflow_step,
                job_type=job_type,
                title=data['title'],
                description=data.get('description', ''),
                start_time=start_time,
                end_time=end_time,
                required_members=int(data.get('required_members', 1)),
                booked_by=profile
            )
        
        return JsonResponse({
            'success': True,
            'booking_id': booking.id,
            'message': f'Booking "{booking.title}" created successfully for {team.name}'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Unexpected error: {str(e)}'})


@login_required
@require_organization_access
def booking_detail(request, booking_id):
    """Get booking details"""
    profile = get_user_profile(request)
    
    if not profile:
        return JsonResponse({'error': 'No profile found'}, status=403)
    
    try:
        booking = TeamBooking.objects.select_related(
            'team', 'work_item', 'work_item__workflow', 
            'booked_by', 'job_type'
        ).get(
            id=booking_id,
            team__organization=profile.organization
        )
    except TeamBooking.DoesNotExist:
        return JsonResponse({'error': 'Booking not found'}, status=404)
    
    return JsonResponse({
        'id': booking.id,
        'title': booking.title,
        'description': booking.description,
        'team': {
            'id': booking.team.id,
            'name': booking.team.name,
            'color': booking.team.color
        },
        'work_item': {
            'id': booking.work_item.id,
            'title': booking.work_item.title,
            'workflow': booking.work_item.workflow.name,
            'priority': booking.work_item.priority
        } if booking.work_item else None,
        'start_time': booking.start_time.isoformat(),
        'end_time': booking.end_time.isoformat(),
        'required_members': booking.required_members,
        'is_completed': booking.is_completed,
        'completed_at': booking.completed_at.isoformat() if booking.completed_at else None,
        'booked_by': {
            'name': booking.booked_by.user.get_full_name() if booking.booked_by and booking.booked_by.user else 'System',
            'email': booking.booked_by.user.email if booking.booked_by and booking.booked_by.user else ''
        } if booking.booked_by else None,
        'job_type': {
            'id': booking.job_type.id,
            'name': booking.job_type.name,
            'color': booking.job_type.color
        } if booking.job_type else None,
        'created_at': booking.created_at.isoformat(),
        'updated_at': booking.updated_at.isoformat()
    })


@login_required
@require_business_organization
@require_POST
def update_booking(request, booking_id):
    """Update a team booking"""
    try:
        profile = get_user_profile(request)
        if not profile:
            return JsonResponse({'success': False, 'error': 'No profile found'})
        
        try:
            booking = TeamBooking.objects.get(
                id=booking_id,
                team__organization=profile.organization
            )
        except TeamBooking.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Booking not found'})
        
        data = json.loads(request.body)
        
        # Update fields that are provided
        updated_fields = []
        
        if 'title' in data:
            booking.title = data['title']
            updated_fields.append('title')
            
        if 'description' in data:
            booking.description = data['description']
            updated_fields.append('description')
            
        if 'start_time' in data:
            try:
                booking.start_time = datetime.fromisoformat(data['start_time'].replace('Z', '+00:00'))
                updated_fields.append('start_time')
            except ValueError:
                return JsonResponse({'success': False, 'error': 'Invalid start_time format'})
                
        if 'end_time' in data:
            try:
                booking.end_time = datetime.fromisoformat(data['end_time'].replace('Z', '+00:00'))
                updated_fields.append('end_time')
            except ValueError:
                return JsonResponse({'success': False, 'error': 'Invalid end_time format'})
                
        if 'required_members' in data:
            try:
                booking.required_members = int(data['required_members'])
                updated_fields.append('required_members')
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'error': 'Invalid required_members value'})
        
        # Validate times if both were updated
        if booking.start_time >= booking.end_time:
            return JsonResponse({'success': False, 'error': 'Start time must be before end time'})
        
        with transaction.atomic():
            booking.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Booking updated successfully. Updated fields: {", ".join(updated_fields)}'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Unexpected error: {str(e)}'})


@login_required
@require_business_organization
@require_POST
def delete_booking(request, booking_id):
    """Delete a team booking"""
    try:
        profile = get_user_profile(request)
        if not profile:
            return JsonResponse({'success': False, 'error': 'No profile found'})
        
        try:
            booking = TeamBooking.objects.get(
                id=booking_id,
                team__organization=profile.organization
            )
        except TeamBooking.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Booking not found'})
        
        # Store booking info for response
        booking_title = booking.title
        team_name = booking.team.name
        
        # Check if booking can be deleted (not completed and not started)
        if booking.is_completed:
            return JsonResponse({'success': False, 'error': 'Cannot delete completed booking'})
        
        with transaction.atomic():
            booking.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Booking "{booking_title}" for team "{team_name}" deleted successfully'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Unexpected error: {str(e)}'})


@login_required
@require_business_organization
def create_booking_for_work_item(request, work_item_id, step_id):
    """Create a booking for a specific work item and workflow step"""
    try:
        profile = get_user_profile(request)
        if not profile:
            messages.error(request, 'No profile found')
            return redirect('cflows:work_items_list')
        
        # Get the work item and step
        try:
            work_item = WorkItem.objects.select_related('workflow', 'current_step').get(
                id=work_item_id,
                workflow__organization=profile.organization
            )
            
            workflow_step = WorkflowStep.objects.get(
                id=step_id,
                workflow=work_item.workflow
            )
        except (WorkItem.DoesNotExist, WorkflowStep.DoesNotExist):
            messages.error(request, 'Work item or workflow step not found')
            return redirect('cflows:work_item_detail', work_item_id=work_item_id)
        
        # Check if step requires booking
        if not workflow_step.requires_booking:
            messages.error(request, 'This workflow step does not require booking')
            return redirect('cflows:work_item_detail', work_item_id=work_item_id)
        
        # Check if step has assigned team
        if not workflow_step.assigned_team:
            messages.error(request, 'No team assigned to this workflow step')
            return redirect('cflows:work_item_detail', work_item_id=work_item_id)
        
        if request.method == 'POST':
            try:
                # Get form data
                title = request.POST.get('title') or f"{work_item.title} - {workflow_step.name}"
                description = request.POST.get('description') or f"Booking for work item: {work_item.title}"
                start_date = request.POST.get('start_date')
                start_time = request.POST.get('start_time')
                duration_hours = float(request.POST.get('duration_hours', workflow_step.estimated_duration_hours or 2.0))
                required_members = int(request.POST.get('required_members', 1))
                
                # Combine date and time
                start_datetime = timezone.datetime.strptime(f"{start_date} {start_time}", "%Y-%m-%d %H:%M")
                start_datetime = timezone.make_aware(start_datetime)
                end_datetime = start_datetime + timezone.timedelta(hours=duration_hours)
                
                # Create booking
                with transaction.atomic():
                    booking = TeamBooking.objects.create(
                        title=title,
                        description=description,
                        team=workflow_step.assigned_team,
                        work_item=work_item,
                        workflow_step=workflow_step,
                        start_time=start_datetime,
                        end_time=end_datetime,
                        required_members=required_members,
                        booked_by=profile
                    )
                
                messages.success(request, f'Booking created successfully: {booking.title}')
                return redirect('cflows:work_item_detail', work_item_id=work_item.id)
                
            except (ValueError, TypeError) as e:
                messages.error(request, f'Invalid data provided: {str(e)}')
            except Exception as e:
                messages.error(request, f'Error creating booking: {str(e)}')
        
        # Get suggested default values
        suggested_start = timezone.now() + timezone.timedelta(hours=1)
        suggested_duration = workflow_step.estimated_duration_hours or 2.0
        
        context = {
            'profile': profile,
            'work_item': work_item,
            'workflow_step': workflow_step,
            'team': workflow_step.assigned_team,
            'suggested_start_date': suggested_start.strftime('%Y-%m-%d'),
            'suggested_start_time': suggested_start.strftime('%H:%M'),
            'suggested_duration': suggested_duration,
            'default_title': f"{work_item.title} - {workflow_step.name}",
        }
        
        return render(request, 'cflows/create_work_item_booking.html', context)
        
    except Exception as e:
        messages.error(request, f'Unexpected error: {str(e)}')
        return redirect('cflows:work_items_list')


@login_required
@require_POST
@require_organization_access
def save_calendar_view(request):
    """Save the current calendar filter configuration as a named view"""
    from .models import CalendarView
    
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'success': False, 'message': 'User profile not found'})
    
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        is_default = data.get('is_default', False)
        
        if not name:
            return JsonResponse({'success': False, 'message': 'View name is required'})
        
        # Get current filters from URL query string
        teams = request.GET.getlist('team')
        job_types = request.GET.getlist('job_type') 
        workflows = request.GET.getlist('workflow')
        status = request.GET.get('status', '')
        event_type = request.GET.get('event_type', '')
        booked_by = request.GET.get('booked_by', '')
        
        # Create or update the view
        calendar_view, created = CalendarView.objects.update_or_create(
            user=profile,
            name=name,
            defaults={
                'teams': [int(t) for t in teams if t.isdigit()],
                'job_types': [int(jt) for jt in job_types if jt.isdigit()],
                'workflows': [int(w) for w in workflows if w.isdigit()],
                'status': status,
                'event_type': event_type,
                'booked_by': booked_by,
                'is_default': is_default
            }
        )
        
        return JsonResponse({
            'success': True, 
            'message': f'View "{name}" {"created" if created else "updated"} successfully',
            'view_id': calendar_view.id
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error saving view: {str(e)}'})


@login_required 
@require_organization_access
def load_calendar_view(request, view_id):
    """Load a saved calendar view by redirecting with the appropriate filters"""
    from .models import CalendarView
    
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'success': False, 'message': 'User profile not found'})
    
    try:
        calendar_view = get_object_or_404(CalendarView, id=view_id, user=profile)
        
        # Build query parameters from the saved view
        params = []
        
        for team_id in calendar_view.teams:
            params.append(f'team={team_id}')
        
        for job_type_id in calendar_view.job_types:
            params.append(f'job_type={job_type_id}')
            
        for workflow_id in calendar_view.workflows:
            params.append(f'workflow={workflow_id}')
            
        if calendar_view.status:
            params.append(f'status={calendar_view.status}')
            
        if calendar_view.event_type:
            params.append(f'event_type={calendar_view.event_type}')
            
        if calendar_view.booked_by:
            params.append(f'booked_by={calendar_view.booked_by}')
        
        query_string = '&'.join(params)
        redirect_url = f'/services/cflows/calendar/{"?" + query_string if query_string else ""}'
        
        return redirect(redirect_url)
        
    except CalendarView.DoesNotExist:
        messages.error(request, 'Calendar view not found')
        return redirect('cflows:calendar')
    except Exception as e:
        messages.error(request, f'Error loading view: {str(e)}')
        return redirect('cflows:calendar')


@login_required
@require_POST  
@require_organization_access
def delete_calendar_view(request, view_id):
    """Delete a saved calendar view"""
    from .models import CalendarView
    
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'success': False, 'message': 'User profile not found'})
    
    try:
        calendar_view = get_object_or_404(CalendarView, id=view_id, user=profile)
        view_name = calendar_view.name
        calendar_view.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'View "{view_name}" deleted successfully'
        })
        
    except CalendarView.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Calendar view not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error deleting view: {str(e)}'})


@login_required
@require_organization_access 
def get_saved_views(request):
    """Get all saved calendar views for the current user"""
    from .models import CalendarView
    
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'success': False, 'message': 'User profile not found'})
    
    views = CalendarView.objects.filter(user=profile).order_by('name')
    
    views_data = []
    for view in views:
        views_data.append({
            'id': view.id,
            'name': view.name,
            'is_default': view.is_default,
            'created_at': view.created_at.strftime('%Y-%m-%d %H:%M')
        })
    
    return JsonResponse({'success': True, 'views': views_data})
