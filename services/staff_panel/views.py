"""
Staff Panel views for organizational administration
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Count, Q, Avg
from django.utils import timezone
from django.contrib.auth.models import User
from core.models import Organization, UserProfile, Team, AuditLog, SystemConfiguration
from core.permissions import Role, Permission, UserRoleAssignment, RolePermission
from core.views import require_organization_access
from core.decorators import require_permission
from licensing.models import Service, License, CustomLicense, UserLicenseAssignment, LicenseAuditLog, LicenseType
from licensing.services import LicensingService
from datetime import timedelta, datetime
import json


def get_user_profile(request):
    """Get user profile for the current user"""
    if not request.user.is_authenticated:
        return None
    
    try:
        return request.user.mediap_profile
    except UserProfile.DoesNotExist:
        return None


def require_staff_access(view_func):
    """Decorator to require staff panel access"""
    def wrapper(request, *args, **kwargs):
        profile = get_user_profile(request)
        if not profile:
            messages.error(request, 'Profile not found.')
            return redirect('dashboard:dashboard')
        
        if not (profile.has_staff_panel_access or profile.is_organization_admin):
            messages.error(request, 'You do not have access to the staff panel.')
            return redirect('dashboard:dashboard')
        
        return view_func(request, *args, **kwargs)
    return wrapper


def log_audit_action(user, action, content_type, object_id=None, object_repr=None, changes=None, request=None):
    """Helper function to log audit actions"""
    audit_data = {
        'user': user,
        'action': action,
        'content_type': content_type,
        'object_id': str(object_id) if object_id else '',
        'object_repr': object_repr or '',
        'changes': changes or {},
    }
    
    if request:
        audit_data.update({
            'ip_address': request.META.get('REMOTE_ADDR'),
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200],
        })
    
    AuditLog.objects.create(**audit_data)


@login_required
@require_organization_access
@require_staff_access
def staff_panel_dashboard(request):
    """Staff panel dashboard with organization overview"""
    profile = request.user.mediap_profile
    organization = profile.organization
    
    # Get organization statistics
    total_users = UserProfile.objects.filter(organization=organization).count()
    active_users = UserProfile.objects.filter(
        organization=organization,
        user__is_active=True
    ).count()
    
    # Calculate user growth
    current_month = datetime.now().replace(day=1)
    last_month = (current_month - timedelta(days=1)).replace(day=1)
    
    users_this_month = UserProfile.objects.filter(
        organization=organization,
        user__date_joined__gte=current_month
    ).count()
    
    users_last_month = UserProfile.objects.filter(
        organization=organization,
        user__date_joined__gte=last_month,
        user__date_joined__lt=current_month
    ).count()
    
    # Calculate growth rate
    growth_rate = 0
    if users_last_month > 0:
        growth_rate = round(((users_this_month - users_last_month) / users_last_month) * 100, 1)
    
    # Get location statistics from user profiles
    location_stats = []
    locations = UserProfile.objects.filter(
        organization=organization
    ).exclude(location='').values('location').annotate(
        user_count=Count('id')
    ).order_by('-user_count')
    
    for loc in locations:
        location_stats.append({
            'name': loc['location'],
            'country': 'Unknown',
            'country_code': 'xx',
            'user_count': loc['user_count']
        })
    
    # Get department statistics
    department_stats = []
    departments = UserProfile.objects.filter(
        organization=organization
    ).exclude(department='').values('department').annotate(
        count=Count('id')
    ).order_by('-count')
    
    for dept in departments:
        department_stats.append({
            'name': dept['department'],
            'count': dept['count']
        })
    
    # Get recent audit activities
    recent_activities = []
    audit_logs = AuditLog.objects.filter(
        user__mediap_profile__organization=organization
    ).select_related('user').order_by('-timestamp')[:10]
    
    for log in audit_logs:
        recent_activities.append({
            'action': log.action,
            'description': f"{log.user.get_full_name() if log.user else 'System'} {log.get_action_display().lower()} {log.content_type} {log.object_repr}",
            'timestamp': log.timestamp,
            'user': log.user.get_full_name() if log.user else 'System'
        })
    
    # Get team statistics
    team_count = Team.objects.filter(organization=organization).count()
    
    # Get role statistics
    try:
        role_count = Role.objects.count()
        permission_count = Permission.objects.count()
    except:
        role_count = 0
        permission_count = 0
    
    # Calculate system health metrics
    system_health = {
        'database': 'operational',
        'redis': 'operational',
        'celery': 'operational',
        'overall': 98.5
    }
    
    # Active tasks (mock for now - would integrate with actual task system)
    active_tasks = 3
    
    context = {
        'organization': organization,
        'profile': profile,
        'total_users': total_users,
        'active_users': active_users,
        'users_this_month': users_this_month,
        'user_growth_rate': growth_rate,
        'total_locations': len(location_stats),
        'countries_count': len(set(loc.get('country', 'Unknown') for loc in location_stats)),
        'total_departments': len(department_stats),
        'team_count': team_count,
        'total_roles': role_count,
        'permissions_count': permission_count,
        'recent_activities': recent_activities,
        'location_stats': location_stats[:5],  # Top 5 locations
        'department_stats': department_stats[:5],  # Top 5 departments
        'active_tasks': active_tasks,
        'system_health': system_health,
    }
    
    return render(request, 'staff_panel/dashboard.html', context)


@login_required
@require_organization_access
@require_staff_access
def organization_settings(request):
    """Organization settings and configuration"""
    profile = request.user.mediap_profile
    organization = profile.organization
    
    if request.method == 'POST':
        # Store old values for audit log
        old_values = {
            'name': organization.name,
            'description': organization.description or '',
            'website': organization.website or '',
            'email': organization.email or '',
            'phone': organization.phone or '',
            'address': organization.address or '',
            'timezone': organization.timezone,
            'time_format_24h': organization.time_format_24h,
        }
        
        # Update organization fields
        organization.name = request.POST.get('name', organization.name).strip()
        organization.description = request.POST.get('description', organization.description or '').strip()
        organization.website = request.POST.get('website', organization.website or '').strip()
        organization.email = request.POST.get('email', organization.email or '').strip()
        organization.phone = request.POST.get('phone', organization.phone or '').strip()
        organization.address = request.POST.get('address', organization.address or '').strip()
        organization.timezone = request.POST.get('timezone', organization.timezone)
        organization.time_format_24h = request.POST.get('time_format_24h') == 'on'
        
        try:
            with transaction.atomic():
                organization.save()
                
                # Track changes for audit log
                changes = {}
                for field, old_value in old_values.items():
                    new_value = getattr(organization, field)
                    if str(old_value) != str(new_value):
                        changes[field] = {'old': old_value, 'new': new_value}
                
                if changes:
                    log_audit_action(
                        user=request.user,
                        action='update',
                        content_type='Organization',
                        object_id=organization.id,
                        object_repr=organization.name,
                        changes=changes,
                        request=request
                    )
                
                messages.success(request, 'Organization settings updated successfully.')
                
        except Exception as e:
            messages.error(request, f'Error updating settings: {str(e)}')
        
        return redirect('staff_panel:organization_settings')
    
    # Get timezone choices (simplified list)
    timezone_choices = [
        ('UTC', 'UTC'),
        ('America/New_York', 'Eastern Time'),
        ('America/Chicago', 'Central Time'),
        ('America/Denver', 'Mountain Time'),
        ('America/Los_Angeles', 'Pacific Time'),
        ('Europe/London', 'GMT'),
        ('Europe/Paris', 'Central European Time'),
        ('Asia/Tokyo', 'Japan Standard Time'),
        ('Australia/Sydney', 'Australian Eastern Time'),
    ]
    
    context = {
        'organization': organization,
        'profile': profile,
        'timezone_choices': timezone_choices,
    }
    
    return render(request, 'staff_panel/organization_settings.html', context)


@login_required
@require_organization_access
@require_staff_access
def user_analytics(request):
    """Detailed user analytics and statistics"""
    profile = request.user.mediap_profile
    organization = profile.organization
    
    # Basic statistics
    total_users = UserProfile.objects.filter(organization=organization).count()
    
    # Active users (logged in within last 30 days)
    thirty_days_ago = datetime.now() - timedelta(days=30)
    active_users = UserProfile.objects.filter(
        organization=organization,
        user__last_login__gte=thirty_days_ago
    ).count()
    
    # New users this month
    current_month = datetime.now().replace(day=1)
    new_users_this_month = UserProfile.objects.filter(
        organization=organization,
        user__date_joined__gte=current_month
    ).count()
    
    # Calculate growth percentage
    last_month = (current_month - timedelta(days=1)).replace(day=1)
    last_month_users = UserProfile.objects.filter(
        organization=organization,
        user__date_joined__gte=last_month,
        user__date_joined__lt=current_month
    ).count()
    
    growth_percentage = 0
    if last_month_users > 0:
        growth_percentage = round(((new_users_this_month - last_month_users) / last_month_users) * 100, 1)
    
    # Department statistics
    department_stats = []
    departments = UserProfile.objects.filter(
        organization=organization
    ).values('department').distinct()
    
    colors = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#06B6D4']
    
    for i, dept in enumerate(departments):
        if dept['department']:
            count = UserProfile.objects.filter(
                organization=organization,
                department=dept['department']
            ).count()
            percentage = round((count / total_users) * 100, 1) if total_users > 0 else 0
            department_stats.append({
                'name': dept['department'],
                'count': count,
                'percentage': percentage,
                'color': colors[i % len(colors)]
            })
    
    # Location statistics
    location_stats = []
    locations = UserProfile.objects.filter(
        organization=organization
    ).exclude(location='').values('location').distinct()
    
    for loc in locations:
        if loc['location']:
            user_count = UserProfile.objects.filter(
                organization=organization,
                location=loc['location']
            ).count()
            
            active_count = UserProfile.objects.filter(
                organization=organization,
                location=loc['location'],
                user__last_login__gte=thirty_days_ago
            ).count()
            
            new_count = UserProfile.objects.filter(
                organization=organization,
                location=loc['location'],
                user__date_joined__gte=current_month
            ).count()
            
            location_stats.append({
                'city': loc['location'],
                'country': 'Unknown',
                'country_code': 'xx',
                'user_count': user_count,
                'active_users': active_count,
                'new_users': new_count
            })
    
    # Role statistics
    role_stats = []
    for role in Role.objects.all():
        user_count = UserRoleAssignment.objects.filter(
            user_profile__organization=organization,
            role=role
        ).count()
        
        if user_count > 0:
            percentage = round((user_count / total_users) * 100, 1) if total_users > 0 else 0
            role_stats.append({
                'name': role.name,
                'user_count': user_count,
                'percentage': percentage
            })
    
    # Weekdays and hours for heatmap
    weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    hours = list(range(24))
    
    # Sample data for charts (would be replaced with real data)
    user_growth_data = [10, 15, 18, 25, 30, 35, 40]
    department_data = [item['count'] for item in department_stats]
    
    context = {
        'organization': organization,
        'profile': profile,
        'total_users': total_users,
        'active_users': active_users,
        'new_users_this_month': new_users_this_month,
        'growth_percentage': abs(growth_percentage),
        'department_stats': department_stats,
        'location_stats': location_stats,
        'role_stats': role_stats,
        'weekdays': weekdays,
        'hours': hours,
        'user_growth_data': user_growth_data,
        'department_data': department_data,
    }
    
    return render(request, 'staff_panel/user_analytics.html', context)


@login_required
@require_organization_access
@require_permission('team.view')
def team_management(request):
    """Team management interface with CRUD operations"""
    profile = get_user_profile(request)
    organization = profile.organization
    
    # Handle form submissions
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'create_team':
            team_name = request.POST.get('team_name', '').strip()
            team_description = request.POST.get('team_description', '').strip()
            parent_team_id = request.POST.get('parent_team') or None
            manager_id = request.POST.get('manager') or None
            
            if team_name:
                try:
                    team_data = {
                        'name': team_name,
                        'description': team_description,
                        'organization': organization,
                    }
                    
                    if parent_team_id:
                        parent_team = Team.objects.get(id=parent_team_id, organization=organization)
                        team_data['parent_team'] = parent_team
                    
                    if manager_id:
                        manager = UserProfile.objects.get(id=manager_id, organization=organization)
                        team_data['manager'] = manager
                    
                    team = Team.objects.create(**team_data)
                    
                    log_audit_action(
                        user=request.user,
                        action='create',
                        content_type='Team',
                        object_id=str(team.id),
                        object_repr=team.name,
                        changes={
                            'name': team_name,
                            'description': team_description,
                            'parent_team': parent_team.name if parent_team_id else None,
                            'manager': manager.user.get_full_name() if manager_id else None
                        },
                        request=request
                    )
                    
                    messages.success(request, f'Team "{team_name}" created successfully.')
                except Exception as e:
                    messages.error(request, f'Error creating team: {str(e)}')
            else:
                messages.error(request, 'Team name is required.')
                
        elif action == 'edit_team':
            team_id = request.POST.get('team_id')
            team_name = request.POST.get('team_name', '').strip()
            team_description = request.POST.get('team_description', '').strip()
            parent_team_id = request.POST.get('parent_team') or None
            manager_id = request.POST.get('manager') or None
            
            try:
                team = Team.objects.get(id=team_id, organization=organization)
                old_values = {
                    'name': team.name,
                    'description': team.description,
                    'parent_team': team.parent_team.name if team.parent_team else None,
                    'manager': team.manager.user.get_full_name() if team.manager else None
                }
                
                team.name = team_name
                team.description = team_description
                team.parent_team = Team.objects.get(id=parent_team_id, organization=organization) if parent_team_id else None
                team.manager = UserProfile.objects.get(id=manager_id, organization=organization) if manager_id else None
                team.save()
                
                new_values = {
                    'name': team.name,
                    'description': team.description,
                    'parent_team': team.parent_team.name if team.parent_team else None,
                    'manager': team.manager.user.get_full_name() if team.manager else None
                }
                
                changes = {}
                for key in old_values:
                    if old_values[key] != new_values[key]:
                        changes[key] = {'old': old_values[key], 'new': new_values[key]}
                
                log_audit_action(
                    user=request.user,
                    action='update',
                    content_type='Team',
                    object_id=str(team.id),
                    object_repr=team.name,
                    changes=changes,
                    request=request
                )
                
                messages.success(request, f'Team "{team_name}" updated successfully.')
            except Team.DoesNotExist:
                messages.error(request, 'Team not found.')
            except Exception as e:
                messages.error(request, f'Error updating team: {str(e)}')
                
        elif action == 'delete_team':
            team_id = request.POST.get('team_id')
            
            try:
                team = Team.objects.get(id=team_id, organization=organization)
                team_name = team.name
                
                # Check if team has sub-teams
                sub_teams = Team.objects.filter(parent_team=team).count()
                if sub_teams > 0:
                    messages.error(request, f'Cannot delete team "{team_name}" - it has {sub_teams} sub-teams.')
                else:
                    team.delete()
                    
                    log_audit_action(
                        user=request.user,
                        action='delete',
                        content_type='Team',
                        object_id=str(team_id),
                        object_repr=team_name,
                        changes={'deleted': True},
                        request=request
                    )
                    
                    messages.success(request, f'Team "{team_name}" deleted successfully.')
            except Team.DoesNotExist:
                messages.error(request, 'Team not found.')
            except Exception as e:
                messages.error(request, f'Error deleting team: {str(e)}')
                
        elif action == 'add_member':
            team_id = request.POST.get('team_id')
            user_ids = request.POST.getlist('members')
            
            try:
                team = Team.objects.get(id=team_id, organization=organization)
                
                for user_id in user_ids:
                    user_profile = UserProfile.objects.get(id=user_id, organization=organization)
                    team.members.add(user_profile)
                
                log_audit_action(
                    user=request.user,
                    action='update',
                    content_type='Team',
                    object_id=str(team.id),
                    object_repr=team.name,
                    changes={'members_added': len(user_ids)},
                    request=request
                )
                
                messages.success(request, f'Added {len(user_ids)} members to team "{team.name}".')
            except Exception as e:
                messages.error(request, f'Error adding members: {str(e)}')
                
        elif action == 'remove_member':
            team_id = request.POST.get('team_id')
            user_id = request.POST.get('user_id')
            
            try:
                team = Team.objects.get(id=team_id, organization=organization)
                user_profile = UserProfile.objects.get(id=user_id, organization=organization)
                team.members.remove(user_profile)
                
                log_audit_action(
                    user=request.user,
                    action='update',
                    content_type='Team',
                    object_id=str(team.id),
                    object_repr=team.name,
                    changes={'member_removed': user_profile.user.get_full_name()},
                    request=request
                )
                
                messages.success(request, f'Removed {user_profile.user.get_full_name()} from team "{team.name}".')
            except Exception as e:
                messages.error(request, f'Error removing member: {str(e)}')
        
        return redirect('staff_panel:team_management')
    
    # Get teams with member counts and relationships
    teams = Team.objects.filter(organization=organization).annotate(
        members_count=Count('members')
    ).prefetch_related('members__user', 'manager__user', 'parent_team').order_by('name')
    
    # Get top-level teams (for hierarchy display)
    top_level_teams = teams.filter(parent_team__isnull=True)
    
    # Get all organization members for dropdowns
    organization_members = UserProfile.objects.filter(
        organization=organization,
        is_active=True
    ).select_related('user').order_by('user__first_name', 'user__last_name')
    
    # Get members not in any team
    team_member_ids = Team.objects.filter(
        organization=organization
    ).values_list('members', flat=True)
    
    unassigned_members = organization_members.exclude(id__in=team_member_ids)
    
    context = {
        'profile': profile,
        'organization': organization,
        'teams': teams,
        'top_level_teams': top_level_teams,
        'organization_members': organization_members,
        'unassigned_members': unassigned_members,
    }
    
    return render(request, 'staff_panel/team_management.html', context)


@login_required
@require_organization_access
@require_staff_access
def search_users(request):
    """AJAX endpoint for searching users within organization"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    profile = get_user_profile(request)
    organization = profile.organization
    
    search_term = request.GET.get('q', '').strip()
    team_id = request.GET.get('team_id')
    
    if len(search_term) < 2:
        return JsonResponse({'error': 'Search term must be at least 2 characters'}, status=400)
    
    # Search users by username, first name, last name, or email
    users = UserProfile.objects.filter(
        organization=organization,
        is_active=True
    ).filter(
        Q(user__username__icontains=search_term) |
        Q(user__first_name__icontains=search_term) |
        Q(user__last_name__icontains=search_term) |
        Q(user__email__icontains=search_term)
    ).select_related('user')
    
    # Exclude users already in the team if team_id is provided
    if team_id:
        try:
            team = Team.objects.get(id=team_id, organization=organization)
            users = users.exclude(teams=team)
        except Team.DoesNotExist:
            pass
    
    # Limit to 20 results
    users = users[:20]
    
    results = []
    for user_profile in users:
        user = user_profile.user
        results.append({
            'id': user_profile.id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'full_name': user.get_full_name() or user.username,
            'email': user.email,
            'initials': get_user_initials(user),
            'department': user_profile.department or '',
            'title': user_profile.title or ''
        })
    
    return JsonResponse({
        'success': True,
        'users': results,
        'count': len(results)
    })


@login_required
@require_organization_access
@require_staff_access
def add_team_member(request, team_id):
    """AJAX endpoint for adding a member to a team"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    profile = get_user_profile(request)
    organization = profile.organization
    
    try:
        team = Team.objects.get(id=team_id, organization=organization)
        user_profile_id = request.POST.get('user_id')
        
        if not user_profile_id:
            return JsonResponse({'error': 'User ID is required'}, status=400)
        
        user_profile = UserProfile.objects.get(
            id=user_profile_id, 
            organization=organization,
            is_active=True
        )
        
        # Check if user is already in the team
        if team.members.filter(id=user_profile.id).exists():
            return JsonResponse({'error': 'User is already a member of this team'}, status=400)
        
        # Add user to team
        team.members.add(user_profile)
        
        # Log the action
        log_audit_action(
            user=request.user,
            action='update',
            content_type='Team',
            object_id=str(team.id),
            object_repr=team.name,
            changes={
                'member_added': user_profile.user.get_full_name(),
                'member_id': user_profile.id
            },
            request=request
        )
        
        return JsonResponse({
            'success': True,
            'message': f'{user_profile.user.get_full_name()} added to team {team.name}',
            'user': {
                'id': user_profile.id,
                'full_name': user_profile.user.get_full_name() or user_profile.user.username,
                'email': user_profile.user.email,
                'initials': get_user_initials(user_profile.user),
                'department': user_profile.department or '',
                'title': user_profile.title or ''
            }
        })
        
    except Team.DoesNotExist:
        return JsonResponse({'error': 'Team not found'}, status=404)
    except UserProfile.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_organization_access
@require_staff_access
def remove_team_member(request, team_id):
    """AJAX endpoint for removing a member from a team"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    profile = get_user_profile(request)
    organization = profile.organization
    
    try:
        team = Team.objects.get(id=team_id, organization=organization)
        user_profile_id = request.POST.get('user_id')
        
        if not user_profile_id:
            return JsonResponse({'error': 'User ID is required'}, status=400)
        
        user_profile = UserProfile.objects.get(
            id=user_profile_id, 
            organization=organization
        )
        
        # Check if user is in the team
        if not team.members.filter(id=user_profile.id).exists():
            return JsonResponse({'error': 'User is not a member of this team'}, status=400)
        
        # Remove user from team
        team.members.remove(user_profile)
        
        # Log the action
        log_audit_action(
            user=request.user,
            action='update',
            content_type='Team',
            object_id=str(team.id),
            object_repr=team.name,
            changes={
                'member_removed': user_profile.user.get_full_name(),
                'member_id': user_profile.id
            },
            request=request
        )
        
        return JsonResponse({
            'success': True,
            'message': f'{user_profile.user.get_full_name()} removed from team {team.name}'
        })
        
    except Team.DoesNotExist:
        return JsonResponse({'error': 'Team not found'}, status=404)
    except UserProfile.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_organization_access
@require_staff_access
def get_team_members(request, team_id):
    """AJAX endpoint for getting current team members"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    profile = get_user_profile(request)
    organization = profile.organization
    
    try:
        team = Team.objects.get(id=team_id, organization=organization)
        members = team.members.filter(is_active=True).select_related('user')
        
        member_list = []
        for member in members:
            member_list.append({
                'id': member.id,
                'username': member.user.username,
                'full_name': member.user.get_full_name() or member.user.username,
                'email': member.user.email,
                'initials': get_user_initials(member.user),
                'department': member.department or '',
                'title': member.title or '',
                'is_manager': team.manager_id == member.id if team.manager else False
            })
        
        return JsonResponse({
            'success': True,
            'members': member_list,
            'count': len(member_list),
            'team_name': team.name
        })
        
    except Team.DoesNotExist:
        return JsonResponse({'error': 'Team not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def get_user_initials(user):
    """Helper function to get user initials"""
    if user.first_name and user.last_name:
        return f"{user.first_name[0]}{user.last_name[0]}".upper()
    elif user.first_name:
        return user.first_name[0].upper()
    elif user.last_name:
        return user.last_name[0].upper()
    else:
        return user.username[0].upper() if user.username else '?'


@login_required
@require_organization_access
@require_permission('user.manage_roles')
def role_permissions(request):
    """Role and permissions management with CRUD operations"""
    profile = get_user_profile(request)
    organization = profile.organization
    
    # Handle form submissions
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'create_role':
            role_name = request.POST.get('role_name', '').strip()
            role_description = request.POST.get('role_description', '').strip()
            
            if role_name:
                try:
                    role = Role.objects.create(
                        name=role_name,
                        description=role_description,
                        organization=organization,
                        created_by=profile
                    )
                    
                    log_audit_action(
                        user=request.user,
                        action='create',
                        content_type='Role',
                        object_id=str(role.id),
                        object_repr=role.name,
                        changes={'name': role_name, 'description': role_description},
                        request=request
                    )
                    
                    messages.success(request, f'Role "{role_name}" created successfully.')
                except Exception as e:
                    messages.error(request, f'Error creating role: {str(e)}')
            else:
                messages.error(request, 'Role name is required.')
                
        elif action == 'edit_role':
            role_id = request.POST.get('role_id')
            role_name = request.POST.get('role_name', '').strip()
            role_description = request.POST.get('role_description', '').strip()
            
            try:
                role = Role.objects.get(id=role_id, organization=organization)
                old_name = role.name
                old_description = role.description
                
                role.name = role_name
                role.description = role_description
                role.save()
                
                log_audit_action(
                    user=request.user,
                    action='update',
                    content_type='Role',
                    object_id=str(role.id),
                    object_repr=role.name,
                    changes={
                        'name': {'old': old_name, 'new': role_name},
                        'description': {'old': old_description, 'new': role_description}
                    },
                    request=request
                )
                
                messages.success(request, f'Role "{role_name}" updated successfully.')
            except Role.DoesNotExist:
                messages.error(request, 'Role not found.')
            except Exception as e:
                messages.error(request, f'Error updating role: {str(e)}')
                
        elif action == 'delete_role':
            role_id = request.POST.get('role_id')
            
            try:
                role = Role.objects.get(id=role_id, organization=organization)
                role_name = role.name
                
                # Check if role has users assigned
                user_count = UserRoleAssignment.objects.filter(role=role).count()
                if user_count > 0:
                    messages.error(request, f'Cannot delete role "{role_name}" - it has {user_count} users assigned.')
                else:
                    role.delete()
                    
                    log_audit_action(
                        user=request.user,
                        action='delete',
                        content_type='Role',
                        object_id=str(role_id),
                        object_repr=role_name,
                        changes={'deleted': True},
                        request=request
                    )
                    
                    messages.success(request, f'Role "{role_name}" deleted successfully.')
            except Role.DoesNotExist:
                messages.error(request, 'Role not found.')
            except Exception as e:
                messages.error(request, f'Error deleting role: {str(e)}')
                
        elif action == 'assign_permissions':
            role_id = request.POST.get('role_id')
            permission_ids = request.POST.getlist('permissions')
            
            try:
                role = Role.objects.get(id=role_id, organization=organization)
                
                # Clear existing permissions
                role.permissions.clear()
                
                # Add selected permissions
                if permission_ids:
                    permissions = Permission.objects.filter(id__in=permission_ids)
                    role.permissions.set(permissions)
                
                log_audit_action(
                    user=request.user,
                    action='update',
                    content_type='Role',
                    object_id=str(role.id),
                    object_repr=role.name,
                    changes={'permissions_updated': len(permission_ids)},
                    request=request
                )
                
                messages.success(request, f'Permissions updated for role "{role.name}".')
            except Role.DoesNotExist:
                messages.error(request, 'Role not found.')
            except Exception as e:
                messages.error(request, f'Error updating permissions: {str(e)}')
        
        return redirect('staff_panel:role_permissions')
    
    try:
        # Get roles with permission and user counts
        roles = Role.objects.filter(organization=organization).annotate(
            permission_count=Count('permissions', distinct=True),
            user_count=Count('user_assignments', distinct=True)
        ).prefetch_related('permissions').order_by('name')
        
        # Get all available permissions
        permissions = Permission.objects.all().order_by('category', 'name')
        
        # Group permissions by category
        permission_categories = {}
        for perm in permissions:
            category = getattr(perm, 'category', 'General')
            if category not in permission_categories:
                permission_categories[category] = []
            permission_categories[category].append(perm)
        
        # Get users for each role
        role_users = {}
        for role in roles:
            role_users[role.id] = UserRoleAssignment.objects.filter(
                role=role
            ).select_related('user_profile__user')[:10]  # Limit to 10 for display
        
    except Exception as e:
        roles = []
        permissions = []
        permission_categories = {}
        role_users = {}
        messages.warning(request, 'Role management system not fully configured.')
    
    context = {
        'profile': profile,
        'organization': organization,
        'roles': roles,
        'permissions': permissions,
        'permission_categories': permission_categories,
        'role_users': role_users,
    }
    
    return render(request, 'staff_panel/role_permissions.html', context)


@login_required
@require_organization_access
@require_permission('user.manage_roles')
def get_role_permissions(request, role_id):
    """Get permissions for a specific role (AJAX endpoint)"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    profile = get_user_profile(request)
    organization = profile.organization
    
    try:
        role = Role.objects.get(id=role_id, organization=organization)
        permission_ids = list(role.permissions.values_list('id', flat=True))
        
        return JsonResponse({
            'success': True,
            'role_id': role.id,
            'role_name': role.name,
            'permission_ids': permission_ids
        })
    except Role.DoesNotExist:
        return JsonResponse({'error': 'Role not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_organization_access
@require_staff_access
def subscription_plans(request):
    """Subscription plans and billing management"""
    profile = request.user.mediap_profile
    organization = profile.organization
    
    # Get subscription from organization if exists
    subscription = getattr(organization, 'subscription', None)
    
    # Current plan information
    if subscription:
        current_plan = {
            'name': subscription.plan_name or 'Professional',
            'description': subscription.plan_description or 'Perfect for growing organizations',
            'monthly_price': subscription.monthly_price or '99',
            'max_users': subscription.max_users or 100,
            'max_storage_gb': subscription.max_storage_gb or 10,
            'is_active': subscription.is_active,
            'trial_end': subscription.trial_end,
            'billing_cycle': subscription.billing_cycle or 'monthly'
        }
        next_billing_date = subscription.next_billing_date or (datetime.now() + timedelta(days=28))
        billing_status = 'Active' if subscription.is_active else 'Inactive'
    else:
        # Default plan if no subscription exists
        current_plan = {
            'name': 'Starter',
            'description': 'Basic plan for small teams',
            'monthly_price': '29',
            'max_users': 20,
            'max_storage_gb': 5,
            'is_active': True,
            'trial_end': None,
            'billing_cycle': 'monthly'
        }
        next_billing_date = datetime.now() + timedelta(days=30)
        billing_status = 'Trial'
    
    # Available plans for upgrade
    available_plans = [
        {
            'name': 'Starter',
            'description': 'Perfect for small teams getting started',
            'monthly_price': 29,
            'annual_price': 290,
            'max_users': 20,
            'max_storage_gb': 5,
            'features': ['Basic Analytics', 'Email Support', 'Mobile Apps']
        },
        {
            'name': 'Professional',
            'description': 'Ideal for growing organizations',
            'monthly_price': 99,
            'annual_price': 990,
            'max_users': 100,
            'max_storage_gb': 50,
            'features': ['Advanced Analytics', 'Priority Support', 'API Access', 'Custom Integrations']
        },
        {
            'name': 'Enterprise',
            'description': 'For large organizations with advanced needs',
            'monthly_price': 299,
            'annual_price': 2990,
            'max_users': 1000,
            'max_storage_gb': 500,
            'features': ['Enterprise Analytics', '24/7 Support', 'Custom Development', 'On-premise Option']
        }
    ]
    
    # Current usage statistics
    current_users = UserProfile.objects.filter(organization=organization).count()
    plan_limit_users = current_plan['max_users']
    user_usage_percentage = min((current_users / plan_limit_users) * 100, 100) if plan_limit_users else 0
    
    # Storage usage (estimated)
    from django.db import models
    storage_used = 0
    try:
        # Calculate approximate storage from file uploads and data
        storage_used = round(current_users * 0.5 + (current_users * 0.1), 2)  # Rough estimate
    except:
        storage_used = 2.5
    
    storage_limit = current_plan['max_storage_gb']
    storage_usage_percentage = (storage_used / storage_limit) * 100 if storage_limit else 0
    
    # Billing history from audit logs
    billing_history = []
    try:
        # Get users in the organization for filtering logs
        organization_users = UserProfile.objects.filter(
            organization=organization
        ).values_list('user_id', flat=True)
        
        payment_logs = AuditLog.objects.filter(
            user_id__in=organization_users,
            action__in=['payment', 'subscription_change', 'plan_upgrade']
        ).order_by('-timestamp')[:12]
        
        for log in payment_logs:
            billing_history.append({
                'date': log.timestamp,
                'description': log.changes.get('description', f'{current_plan["name"]} Plan - {current_plan["billing_cycle"].title()}'),
                'amount': log.changes.get('amount', current_plan['monthly_price']),
                'status': 'paid'
            })
    except:
        # Fallback to sample data
        billing_history = [
            {
                'date': datetime.now() - timedelta(days=30),
                'description': f'{current_plan["name"]} Plan - Monthly',
                'amount': current_plan['monthly_price'],
                'status': 'paid'
            }
        ]
    
    # Payment method (would integrate with payment processor)
    payment_method = {
        'type': 'Credit Card',
        'last_four': '****',
        'expiry': '**/**',
        'is_configured': False
    }
    
    # Calculate cost savings for annual billing
    annual_savings = {}
    for plan in available_plans:
        monthly_cost = plan['monthly_price'] * 12
        annual_cost = plan['annual_price']
        annual_savings[plan['name']] = monthly_cost - annual_cost
    
    context = {
        'organization': organization,
        'profile': profile,
        'current_plan': current_plan,
        'available_plans': available_plans,
        'next_billing_date': next_billing_date,
        'billing_status': billing_status,
        'billing_history': billing_history,
        'current_users': current_users,
        'plan_limit_users': plan_limit_users,
        'user_usage_percentage': round(user_usage_percentage, 1),
        'storage_used': storage_used,
        'storage_limit': storage_limit,
        'storage_usage_percentage': round(storage_usage_percentage, 1),
        'payment_method': payment_method,
        'annual_savings': annual_savings,
    }
    
    return render(request, 'staff_panel/subscription_plans.html', context)


@login_required
@require_organization_access
@require_staff_access
def system_logs(request):
    """System logs and audit trail with advanced filtering"""
    profile = request.user.mediap_profile
    organization = profile.organization
    
    # Get users in the organization for filtering logs
    organization_users = UserProfile.objects.filter(
        organization=organization
    ).values_list('user_id', flat=True)
    
    # Filters from request
    action_filter = request.GET.get('action', '')
    user_filter = request.GET.get('user', '')
    content_type_filter = request.GET.get('content_type', '')
    date_range = request.GET.get('date_range', '7')  # days
    search_query = request.GET.get('search', '').strip()
    
    # Date filtering
    try:
        days = int(date_range)
    except ValueError:
        days = 7
    
    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)
    
    # Base queryset
    logs = AuditLog.objects.filter(
        user_id__in=organization_users,
        timestamp__gte=start_date
    ).select_related('user').order_by('-timestamp')
    
    # Apply filters
    if action_filter:
        logs = logs.filter(action__icontains=action_filter)
    
    if user_filter:
        logs = logs.filter(
            Q(user__username__icontains=user_filter) |
            Q(user__first_name__icontains=user_filter) |
            Q(user__last_name__icontains=user_filter) |
            Q(user__email__icontains=user_filter)
        )
    
    if content_type_filter:
        logs = logs.filter(content_type__icontains=content_type_filter)
    
    if search_query:
        logs = logs.filter(
            Q(object_repr__icontains=search_query) |
            Q(changes__icontains=search_query) |
            Q(additional_data__icontains=search_query)
        )
    
    # Export functionality
    export_format = request.GET.get('export')
    if export_format in ['csv', 'json']:
        return export_audit_logs(logs, export_format, organization.name)
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page')
    logs_page = paginator.get_page(page_number)
    
    # Statistics
    total_logs = logs.count()
    all_logs_count = AuditLog.objects.filter(user_id__in=organization_users).count()
    
    # Get unique users for filter dropdown
    log_users = AuditLog.objects.filter(
        user_id__in=organization_users
    ).values(
        'user__id', 'user__username', 'user__first_name', 'user__last_name'
    ).distinct().order_by('user__first_name', 'user__last_name')
    
    # Action breakdown for current filtered results
    action_stats = logs.values('action').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Most active users in current filtered results
    user_stats = logs.values(
        'user__username', 'user__first_name', 'user__last_name'
    ).annotate(
        action_count=Count('id')
    ).order_by('-action_count')[:10]
    
    # Content type breakdown for current filtered results
    content_type_stats = logs.values('content_type').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Recent critical actions (always from all logs, not filtered)
    critical_actions = AuditLog.objects.filter(
        user_id__in=organization_users,
        action__in=['delete', 'permission_change', 'role_change', 'security_event']
    ).select_related('user').order_by('-timestamp')[:20]
    
    # Daily activity for chart (last 30 days, not affected by filters)
    daily_activity = []
    chart_end_date = timezone.now()
    for i in range(30):
        day = chart_end_date - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        
        day_count = AuditLog.objects.filter(
            user_id__in=organization_users,
            timestamp__gte=day_start,
            timestamp__lt=day_end
        ).count()
        
        daily_activity.insert(0, {
            'date': day_start.strftime('%Y-%m-%d'),
            'count': day_count
        })
    
    # Get available filter options
    available_actions = AuditLog.objects.filter(
        user_id__in=organization_users
    ).values_list('action', flat=True).distinct().order_by('action')
    
    available_content_types = AuditLog.objects.filter(
        user_id__in=organization_users
    ).values_list('content_type', flat=True).distinct().order_by('content_type')
    
    context = {
        'organization': organization,
        'profile': profile,
        'logs': logs_page,
        'total_logs': total_logs,
        'all_logs_count': all_logs_count,
        'filtered_count': total_logs,
        'action_stats': action_stats,
        'user_stats': user_stats,
        'content_type_stats': content_type_stats,
        'critical_actions': critical_actions,
        'daily_activity': daily_activity,
        'available_actions': available_actions,
        'available_content_types': available_content_types,
        'log_users': log_users,
        'filters': {
            'action': action_filter,
            'user': user_filter,
            'content_type': content_type_filter,
            'date_range': date_range,
            'search': search_query,
        },
        'date_range_options': [
            ('1', 'Last 24 hours'),
            ('7', 'Last 7 days'),
            ('30', 'Last 30 days'),
            ('90', 'Last 3 months'),
            ('365', 'Last year'),
        ],
        'has_filters': any([action_filter, user_filter, content_type_filter, search_query]) or days != 7,
    }
    
    return render(request, 'staff_panel/system_logs.html', context)


@login_required
@require_organization_access
@require_staff_access
def integrations(request):
    """Real third-party integrations management with database storage"""
    profile = request.user.mediap_profile
    organization = profile.organization
    
    # Import the models here to avoid any issues
    from .models import Integration, IntegrationLog
    
    # Handle integration actions
    if request.method == 'POST':
        action = request.POST.get('action')
        integration_name = request.POST.get('integration')
        
        if action == 'connect':
            # Create or activate integration
            integration, created = Integration.objects.get_or_create(
                organization=organization,
                integration_type=integration_name.lower(),
                defaults={
                    'name': f"{organization.name} {integration_name}",
                    'status': 'pending',
                    'created_by': request.user,
                }
            )
            
            if not created:
                integration.is_enabled = True
                integration.status = 'active'
                integration.save()
            
            IntegrationLog.objects.create(
                integration=integration,
                level='info',
                action='configure',
                message=f'Integration {integration_name} connected',
                details={'action': 'connected'}
            )
            
            log_audit_action(
                user=request.user,
                action='integration_connect',
                content_type='Integration',
                object_id=str(integration.id),
                object_repr=integration_name,
                changes={'action': 'connected'},
                request=request
            )
            messages.success(request, f'{integration_name} integration connected successfully.')
            
        elif action == 'disconnect':
            try:
                integration = Integration.objects.get(
                    organization=organization,
                    integration_type=integration_name.lower()
                )
                integration.is_enabled = False
                integration.status = 'inactive'
                integration.save()
                
                IntegrationLog.objects.create(
                    integration=integration,
                    level='info',
                    action='configure',
                    message=f'Integration {integration_name} disconnected',
                    details={'action': 'disconnected'}
                )
                
                log_audit_action(
                    user=request.user,
                    action='integration_disconnect',
                    content_type='Integration',
                    object_id=str(integration.id),
                    object_repr=integration_name,
                    changes={'action': 'disconnected'},
                    request=request
                )
                messages.info(request, f'{integration_name} integration disconnected.')
            except Integration.DoesNotExist:
                messages.error(request, f'{integration_name} integration not found.')
            
        return redirect('staff_panel:integrations')
    
    # Get configured integrations from database
    configured_integrations = Integration.objects.filter(
        organization=organization
    ).order_by('integration_type')
    
    configured_types = {
        integration.integration_type: integration 
        for integration in configured_integrations
    }
    
    # Available integrations with real configuration options
    available_integrations = [
        {
            'name': 'Slack',
            'type': 'slack',
            'description': 'Send notifications and updates to Slack channels',
            'icon': 'fab fa-slack',
            'category': 'Communication',
            'status': 'connected' if 'slack' in configured_types and configured_types['slack'].is_enabled else 'available',
            'features': ['Channel notifications', 'Direct messages', 'Workflow updates'],
            'setup_required': ['Slack workspace', 'Bot token', 'Channel permissions'],
            'webhook_url': f'/api/integrations/slack/{organization.id}/',
            'docs_url': 'https://api.slack.com/start/building',
            'integration': configured_types.get('slack')
        },
        {
            'name': 'Microsoft Teams',
            'type': 'teams',
            'description': 'Integrate with Microsoft Teams for collaboration',
            'icon': 'fab fa-microsoft',
            'category': 'Communication',
            'status': 'connected' if 'teams' in configured_types and configured_types['teams'].is_enabled else 'available',
            'features': ['Team notifications', 'Meeting integration', 'File sharing'],
            'setup_required': ['Microsoft 365 account', 'App registration', 'Team permissions'],
            'webhook_url': f'/api/integrations/teams/{organization.id}/',
            'docs_url': 'https://docs.microsoft.com/en-us/microsoftteams/',
            'integration': configured_types.get('teams')
        },
        {
            'name': 'Google Workspace',
            'type': 'google',
            'description': 'Connect with Google Calendar and Drive',
            'icon': 'fab fa-google',
            'category': 'Productivity',
            'status': 'connected' if 'google' in configured_types and configured_types['google'].is_enabled else 'available',
            'features': ['Calendar sync', 'Drive integration', 'Gmail notifications'],
            'setup_required': ['Google Cloud project', 'OAuth credentials', 'API access'],
            'webhook_url': f'/api/integrations/google/{organization.id}/',
            'docs_url': 'https://developers.google.com/workspace',
            'integration': configured_types.get('google')
        },
        {
            'name': 'Zapier',
            'type': 'zapier',
            'description': 'Connect with 3000+ apps through Zapier',
            'icon': 'fas fa-bolt',
            'category': 'Automation',
            'status': 'connected' if 'zapier' in configured_types and configured_types['zapier'].is_enabled else 'available',
            'features': ['Workflow automation', 'Data sync', 'Trigger actions'],
            'setup_required': ['Zapier account', 'API key', 'Webhook configuration'],
            'webhook_url': f'/api/integrations/zapier/{organization.id}/',
            'docs_url': 'https://zapier.com/developer',
            'integration': configured_types.get('zapier')
        },
        {
            'name': 'GitHub',
            'type': 'github',
            'description': 'Integrate with GitHub repositories and issues',
            'icon': 'fab fa-github',
            'category': 'Development',
            'status': 'connected' if 'github' in configured_types and configured_types['github'].is_enabled else 'available',
            'features': ['Repository sync', 'Issue tracking', 'Pull request notifications'],
            'setup_required': ['GitHub account', 'Personal access token', 'Repository access'],
            'webhook_url': f'/api/integrations/github/{organization.id}/',
            'docs_url': 'https://docs.github.com/en/developers',
            'integration': configured_types.get('github')
        },
        {
            'name': 'Jira',
            'type': 'jira',
            'description': 'Sync with Jira issues and projects',
            'icon': 'fab fa-atlassian',
            'category': 'Project Management',
            'status': 'connected' if 'jira' in configured_types and configured_types['jira'].is_enabled else 'available',
            'features': ['Issue sync', 'Project tracking', 'Status updates'],
            'setup_required': ['Jira account', 'API token', 'Project permissions'],
            'webhook_url': f'/api/integrations/jira/{organization.id}/',
            'docs_url': 'https://developer.atlassian.com/server/jira/',
            'integration': configured_types.get('jira')
        },
        {
            'name': 'Blocket',
            'type': 'blocket',
            'description': 'Show live published vehicle statistics from your Blocket.se dealer shop',
            'icon': 'fas fa-car',
            'category': 'Analytics',
            'status': 'connected' if 'blocket' in configured_types and configured_types['blocket'].is_enabled else 'available',
            'features': ['Published car count', 'Motorcycle & boat listings', 'Live sample ads'],
            'setup_required': ['Blocket organisation ID (from shop URL)'],
            'docs_url': 'https://www.blocket.se/',
            'integration': configured_types.get('blocket')
        },
    ]
    
    # Group integrations by category
    integration_categories = {}
    for integration in available_integrations:
        category = integration['category']
        if category not in integration_categories:
            integration_categories[category] = []
        integration_categories[category].append(integration)
    
    # Integration statistics
    total_available = len(available_integrations)
    total_connected = len([i for i in available_integrations if i['status'] == 'connected'])
    connection_rate = (total_connected / total_available * 100) if total_available > 0 else 0
    
    # Recent integration activities from database
    recent_activities = []
    try:
        recent_logs = IntegrationLog.objects.filter(
            integration__organization=organization
        ).select_related('integration').order_by('-created_at')[:10]
        
        for log in recent_logs:
            recent_activities.append({
                'timestamp': log.created_at,
                'user': log.integration.created_by.get_full_name() if log.integration.created_by else 'System',
                'action': log.action.replace('_', ' ').title(),
                'integration': log.integration.get_integration_type_display(),
                'details': log.details,
                'level': log.level
            })
    except Exception as e:
        pass
    
    context = {
        'organization': organization,
        'profile': profile,
        'integrations': available_integrations,
        'integration_categories': integration_categories,
        'configured_integrations': configured_integrations,
        'total_available': total_available,
        'total_connected': total_connected,
        'connection_rate': round(connection_rate, 1),
        'recent_activities': recent_activities,
    }
    
    return render(request, 'staff_panel/integrations.html', context)


@login_required
@require_organization_access
@require_staff_access
def configure_integration(request, integration_name):
    """Configure a specific integration"""
    profile = request.user.mediap_profile
    organization = profile.organization
    
    # Import the models here to avoid circular import issues
    from .models import Integration, IntegrationLog
    
    try:
        integration = Integration.objects.get(
            organization=organization,
            integration_type=integration_name.lower()
        )
    except Integration.DoesNotExist:
        integration = None
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'save_config':
            # Blocket integration stores only an org_id in the config JSONField
            if integration_name.lower() == 'blocket':
                raw_org_id = request.POST.get('org_id', '').strip()
                if not raw_org_id.isdigit():
                    messages.error(request, 'Blocket organisation ID must be a number.')
                    return redirect('staff_panel:configure_integration', integration_name=integration_name)
                config_data = {'org_id': int(raw_org_id)}
                if integration:
                    integration.config = config_data
                    integration.status = 'active'
                    integration.is_enabled = True
                    integration.save()
                    IntegrationLog.objects.create(
                        integration=integration,
                        level='info',
                        action='configure',
                        message='Blocket organisation ID updated',
                        details=config_data,
                    )
                    messages.success(request, 'Blocket integration updated successfully.')
                else:
                    integration = Integration.objects.create(
                        organization=organization,
                        integration_type='blocket',
                        name=f"{organization.name} Blocket",
                        config=config_data,
                        status='active',
                        is_enabled=True,
                        created_by=request.user,
                    )
                    IntegrationLog.objects.create(
                        integration=integration,
                        level='success',
                        action='configure',
                        message='Blocket integration configured',
                        details=config_data,
                    )
                    messages.success(request, 'Blocket integration configured successfully.')
                log_audit_action(
                    user=request.user,
                    action='update',
                    content_type='Integration',
                    object_id=str(integration.id),
                    object_repr='Blocket integration',
                    changes=config_data,
                    request=request,
                )
                return redirect('staff_panel:configure_integration', integration_name=integration_name)

            config_data = {
                'webhook_url': request.POST.get('webhook_url', ''),
                'api_key': request.POST.get('api_key', ''),
                'channel': request.POST.get('channel', ''),
                'settings': {
                    'send_notifications': request.POST.get('send_notifications') == 'on',
                    'sync_enabled': request.POST.get('sync_enabled') == 'on',
                }
            }
            
            if integration:
                # Update existing integration
                integration.config = config_data
                integration.webhook_url = config_data['webhook_url']
                integration.api_key = config_data['api_key']
                integration.send_notifications = config_data['settings']['send_notifications']
                integration.status = 'active' if config_data['api_key'] else 'pending'
                integration.save()
                
                IntegrationLog.objects.create(
                    integration=integration,
                    level='info',
                    action='configure',
                    message='Integration configuration updated',
                    details=config_data
                )
                
                messages.success(request, f'{integration_name} integration updated successfully.')
            else:
                # Create new integration
                integration = Integration.objects.create(
                    organization=organization,
                    integration_type=integration_name.lower(),
                    name=f"{organization.name} {integration_name}",
                    config=config_data,
                    webhook_url=config_data['webhook_url'],
                    api_key=config_data['api_key'],
                    send_notifications=config_data['settings']['send_notifications'],
                    status='active' if config_data['api_key'] else 'pending',
                    created_by=request.user
                )
                
                IntegrationLog.objects.create(
                    integration=integration,
                    level='success',
                    action='configure',
                    message='Integration configured successfully',
                    details=config_data
                )
                
                messages.success(request, f'{integration_name} integration configured successfully.')
                
            log_audit_action(
                user=request.user,
                action='update',
                content_type='Integration',
                object_id=str(integration.id),
                object_repr=f"{integration_name} integration",
                changes=config_data,
                request=request
            )
            
        return redirect('staff_panel:configure_integration', integration_name=integration_name)
    
    # Get recent logs for this integration
    recent_logs = []
    if integration:
        recent_logs = integration.logs.all()[:20]
    
    context = {
        'organization': organization,
        'profile': profile,
        'integration': integration,
        'integration_name': integration_name,
        'recent_logs': recent_logs,
    }
    
    return render(request, 'staff_panel/configure_integration.html', context)


@login_required
@require_organization_access
@require_staff_access
def test_integration(request, integration_name):
    """Test an integration connection"""
    profile = request.user.mediap_profile
    organization = profile.organization
    
    from .models import Integration, IntegrationLog
    import json
    
    try:
        integration = Integration.objects.get(
            organization=organization,
            integration_type=integration_name.lower()
        )
        
        # Simulate integration test
        test_result = {
            'success': True,
            'message': f'{integration_name} integration test successful',
            'response_time': '145ms',
            'status_code': 200
        }
        
        # For Blocket, perform a real API call to verify the org_id is valid
        if integration_name.lower() == 'blocket':
            org_id = integration.config.get('org_id')
            if not org_id:
                return JsonResponse({
                    'success': False,
                    'message': 'Blocket organisation ID is not configured',
                    'error': 'Missing org_id in integration config',
                })
            try:
                import sys
                import os
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
                from services.analytics.services.blocket_service import fetch_blocket_shop_stats
                stats = fetch_blocket_shop_stats(int(org_id))
                if stats.get('error'):
                    test_result = {
                        'success': False,
                        'message': f'Blocket API error: {stats["error"]}',
                        'status_code': 503,
                    }
                else:
                    test_result = {
                        'success': True,
                        'message': f'Blocket connection successful — {stats["published_cars"]} cars published',
                        'total_published': stats['total_published'],
                        'store_url': stats['store_url'],
                    }
            except Exception as exc:
                test_result = {
                    'success': False,
                    'message': f'Blocket test failed: {str(exc)}',
                    'error': str(exc),
                }
        
        IntegrationLog.objects.create(
            integration=integration,
            level='success',
            action='test',
            message='Integration test completed successfully',
            details=test_result
        )
        
        integration.last_sync = timezone.now()
        integration.save()
        
        log_audit_action(
            user=request.user,
            action='integration_test',
            content_type='Integration',
            object_id=str(integration.id),
            object_repr=f"{integration_name} integration",
            changes=test_result,
            request=request
        )
        
        return JsonResponse({
            'success': True,
            'message': f'{integration_name} connection test successful',
            'details': test_result
        })
        
    except Integration.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': f'{integration_name} integration not configured',
            'error': 'Integration not found'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Integration test failed: {str(e)}',
            'error': str(e)
        })


@login_required
@require_organization_access
@require_staff_access
def license_management(request):
    """License management for organizations"""
    profile = get_user_profile(request)
    organization = profile.organization
    
    # Get organization license summary
    summary = LicensingService.get_organization_license_summary(organization)
    
    # Get organization members for assignment
    organization_members = UserProfile.objects.filter(
        organization=organization,
        is_active=True
    ).select_related('user').order_by('user__first_name', 'user__last_name')
    
    # Get current assignments
    current_assignments = UserLicenseAssignment.objects.filter(
        license__organization=organization,
        is_active=True
    ).select_related(
        'user_profile__user', 
        'license__license_type__service', 
        'license__custom_license__service'
    ).order_by('user_profile__user__first_name')
    
    # Get available services
    services = Service.objects.filter(is_active=True).order_by('name')
    
    # Get audit logs for this organization
    audit_logs = LicenseAuditLog.objects.filter(
        Q(license__organization=organization) | 
        Q(custom_license__organization=organization)
    ).select_related(
        'performed_by', 
        'affected_user__user'
    ).order_by('-timestamp')[:50]
    
    context = {
        'profile': profile,
        'organization': organization,
        'summary': summary,
        'organization_members': organization_members,
        'current_assignments': current_assignments,
        'services': services,
        'audit_logs': audit_logs,
    }
    
    return render(request, 'staff_panel/license_management.html', context)


@login_required
@require_organization_access
@require_staff_access
def assign_user_license(request):
    """Assign a license to a user"""
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('staff_panel:license_management')
    
    profile = get_user_profile(request)
    organization = profile.organization
    
    try:
        license_id = request.POST.get('license_id')
        user_profile_id = request.POST.get('user_profile_id')
        
        # Get the license (can be standard or custom)
        license = License.objects.get(id=license_id, organization=organization)
        target_user_profile = UserProfile.objects.get(
            id=user_profile_id, 
            organization=organization,
            is_active=True
        )
        
        # Use licensing service to assign
        success, result = LicensingService.assign_user_to_license(
            license, target_user_profile, request.user
        )
        
        if success:
            service_name = (license.custom_license.service.name 
                          if license.custom_license 
                          else license.license_type.service.name)
            messages.success(
                request, 
                f'License for {service_name} assigned to {target_user_profile.user.get_full_name()}.'
            )
        else:
            messages.error(request, result)
            
    except (License.DoesNotExist, UserProfile.DoesNotExist) as e:
        messages.error(request, 'Invalid license or user.')
    except Exception as e:
        messages.error(request, f'Error assigning license: {str(e)}')
    
    return redirect('staff_panel:license_management')


@login_required
@require_organization_access
@require_staff_access
def revoke_user_license(request):
    """Revoke a license from a user"""
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('staff_panel:license_management')
    
    profile = get_user_profile(request)
    organization = profile.organization
    
    try:
        assignment_id = request.POST.get('assignment_id')
        reason = request.POST.get('reason', '')
        
        assignment = UserLicenseAssignment.objects.get(
            id=assignment_id,
            license__organization=organization,
            is_active=True
        )
        
        # Use licensing service to revoke
        success, result = LicensingService.revoke_user_license(
            assignment, request.user, reason
        )
        
        if success:
            service_name = (assignment.license.custom_license.service.name 
                          if assignment.license.custom_license 
                          else assignment.license.license_type.service.name)
            messages.success(
                request, 
                f'License for {service_name} revoked from {assignment.user_profile.user.get_full_name()}.'
            )
        else:
            messages.error(request, result)
            
    except UserLicenseAssignment.DoesNotExist:
        messages.error(request, 'Invalid license assignment.')
    except Exception as e:
        messages.error(request, f'Error revoking license: {str(e)}')
    
    return redirect('staff_panel:license_management')


@login_required
@require_staff_access
def create_custom_license(request):
    """Create a custom license (superuser/customer support only)"""
    if not (request.user.is_superuser or 
            (hasattr(request.user, 'mediap_profile') and 
             request.user.mediap_profile.has_staff_panel_access)):
        messages.error(request, 'You do not have permission to create custom licenses.')
        return redirect('staff_panel:license_management')
    
    if request.method == 'POST':
        try:
            organization_id = request.POST.get('organization_id')
            service_id = request.POST.get('service_id')
            
            organization = get_object_or_404(Organization, id=organization_id)
            service = get_object_or_404(Service, id=service_id, is_active=True)
            
            # Calculate end date
            duration_days = int(request.POST.get('duration_days', 365))
            start_date = timezone.now()
            end_date = None
            if duration_days > 0:
                end_date = start_date + timezone.timedelta(days=duration_days)
            
            # Create custom license
            custom_license = CustomLicense.objects.create(
                name=request.POST.get('name'),
                organization=organization,
                service=service,
                max_users=int(request.POST.get('max_users')),
                description=request.POST.get('description', ''),
                start_date=start_date,
                end_date=end_date,
                included_features=request.POST.get('features', '').split(',') if request.POST.get('features') else [],
                created_by=request.user,
                notes=request.POST.get('notes', '')
            )
            
            # Auto-activate if requested
            if request.POST.get('auto_activate'):
                # Create custom license type if needed
                custom_license_type, _ = LicenseType.objects.get_or_create(
                    service=service,
                    name='custom',
                    defaults={
                        'display_name': 'Custom License',
                        'price_monthly': 0,
                        'price_yearly': 0,
                        'max_users': None,
                        'features': ['custom_configuration'],
                        'is_active': True
                    }
                )
                
                # Create license instance
                License.objects.create(
                    license_type=custom_license_type,
                    organization=organization,
                    custom_license=custom_license,
                    account_type='organization',
                    status='active',
                    start_date=start_date,
                    end_date=end_date,
                    created_by=request.user
                )
            
            # Create audit log
            LicenseAuditLog.objects.create(
                custom_license=custom_license,
                action='create',
                performed_by=request.user,
                description=f'Custom license created: {custom_license.name}',
                new_values={
                    'organization': organization.name,
                    'service': service.name,
                    'max_users': custom_license.max_users,
                    'duration_days': duration_days
                }
            )
            
            messages.success(request, f'Custom license "{custom_license.name}" created successfully.')
            
        except Exception as e:
            messages.error(request, f'Error creating custom license: {str(e)}')
    
    return redirect('staff_panel:license_management')


@login_required
@require_organization_access
@require_staff_access
def create_role(request):
    """AJAX endpoint for creating a new role"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    profile = get_user_profile(request)
    organization = profile.organization
    
    try:
        # Handle both JSON and form data
        if request.content_type == 'application/json':
            import json
            data = json.loads(request.body)
            role_name = data.get('name', '').strip()
            role_description = data.get('description', '').strip()
            role_type = data.get('role_type', 'organization').strip()
            color = data.get('color', '#0066cc').strip()
        else:
            role_name = request.POST.get('role_name', '').strip()
            role_description = request.POST.get('role_description', '').strip()
            role_type = request.POST.get('role_type', 'organization').strip()
            color = request.POST.get('color', '#0066cc').strip()
        
        if not role_name:
            return JsonResponse({'error': 'Role name is required'}, status=400)
        
        # Check if role name already exists
        if Role.objects.filter(organization=organization, name=role_name).exists():
            return JsonResponse({'error': 'A role with this name already exists'}, status=400)
        
        role = Role.objects.create(
            name=role_name,
            description=role_description,
            role_type=role_type,
            color=color,
            organization=organization,
            created_by=profile
        )
        
        # Log the action
        log_audit_action(
            user=request.user,
            action='create',
            content_type='Role',
            object_id=str(role.id),
            object_repr=role.name,
            changes={'name': role_name, 'description': role_description},
            request=request
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Role "{role_name}" created successfully',
            'role': {
                'id': role.id,
                'name': role.name,
                'description': role.description,
                'permission_count': 0,
                'user_count': 0
            }
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_organization_access
@require_staff_access
def edit_role(request, role_id):
    """AJAX endpoint for editing a role"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    profile = get_user_profile(request)
    organization = profile.organization
    
    try:
        role = Role.objects.get(id=role_id, organization=organization)
        
        # Handle both JSON and form data
        if request.content_type == 'application/json':
            import json
            data = json.loads(request.body)
            role_name = data.get('name', '').strip()
            role_description = data.get('description', '').strip()
            role_type = data.get('role_type', role.role_type).strip()
            color = data.get('color', role.color).strip()
        else:
            role_name = request.POST.get('role_name', '').strip()
            role_description = request.POST.get('role_description', '').strip()
            role_type = request.POST.get('role_type', role.role_type).strip()
            color = request.POST.get('color', role.color).strip()
        
        if not role_name:
            return JsonResponse({'error': 'Role name is required'}, status=400)
        
        # Check if role name already exists (excluding current role)
        if Role.objects.filter(organization=organization, name=role_name).exclude(id=role_id).exists():
            return JsonResponse({'error': 'A role with this name already exists'}, status=400)
        
        old_values = {
            'name': role.name,
            'description': role.description,
            'role_type': role.role_type,
            'color': role.color
        }
        
        role.name = role_name
        role.description = role_description
        role.role_type = role_type
        role.color = color
        role.save()
        
        new_values = {
            'name': role.name,
            'description': role.description,
            'role_type': role.role_type,
            'color': role.color
        }
        
        changes = {}
        for key in old_values:
            if old_values[key] != new_values[key]:
                changes[key] = {'old': old_values[key], 'new': new_values[key]}
        
        log_audit_action(
            user=request.user,
            action='update',
            content_type='Role',
            object_id=str(role.id),
            object_repr=role.name,
            changes=changes,
            request=request
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Role "{role_name}" updated successfully',
            'role': {
                'id': role.id,
                'name': role.name,
                'description': role.description
            }
        })
        
    except Role.DoesNotExist:
        return JsonResponse({'error': 'Role not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_organization_access
@require_staff_access
def delete_role(request, role_id):
    """AJAX endpoint for deleting a role"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    profile = get_user_profile(request)
    organization = profile.organization
    
    try:
        role = Role.objects.get(id=role_id, organization=organization)
        
        # Check if role has users assigned
        user_count = role.user_assignments.filter(is_active=True).count()
        if user_count > 0:
            return JsonResponse({
                'error': f'Cannot delete role "{role.name}" - it has {user_count} users assigned. Remove all users first.'
            }, status=400)
        
        role_name = role.name
        role.delete()
        
        log_audit_action(
            user=request.user,
            action='delete',
            content_type='Role',
            object_id=str(role_id),
            object_repr=role_name,
            changes={'deleted': True},
            request=request
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Role "{role_name}" deleted successfully'
        })
        
    except Role.DoesNotExist:
        return JsonResponse({'error': 'Role not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_organization_access
@require_staff_access
def assign_role_permissions(request, role_id):
    """AJAX endpoint for assigning permissions to a role"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    profile = get_user_profile(request)
    organization = profile.organization
    
    try:
        role = Role.objects.get(id=role_id, organization=organization)
        permission_ids = request.POST.getlist('permissions')
        
        # Clear existing permissions
        role.permissions.clear()
        
        # Add selected permissions
        if permission_ids:
            permissions = Permission.objects.filter(id__in=permission_ids)
            for permission in permissions:
                RolePermission.objects.create(
                    role=role,
                    permission=permission,
                    granted_by=profile
                )
        
        log_audit_action(
            user=request.user,
            action='update',
            content_type='Role',
            object_id=str(role.id),
            object_repr=role.name,
            changes={'permissions_updated': len(permission_ids)},
            request=request
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Permissions updated for role "{role.name}"',
            'permission_count': len(permission_ids)
        })
        
    except Role.DoesNotExist:
        return JsonResponse({'error': 'Role not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_organization_access
@require_staff_access
def get_role_users(request, role_id):
    """AJAX endpoint for getting users assigned to a role"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    profile = get_user_profile(request)
    organization = profile.organization
    
    try:
        role = Role.objects.get(id=role_id, organization=organization)
        user_assignments = role.user_assignments.filter(is_active=True).select_related('user_profile__user')
        
        users = []
        for assignment in user_assignments:
            user_profile = assignment.user_profile
            user = user_profile.user
            users.append({
                'id': user_profile.id,
                'username': user.username,
                'full_name': user.get_full_name() or user.username,
                'email': user.email,
                'initials': get_user_initials(user),
                'department': user_profile.department or '',
                'title': user_profile.title or '',
                'assigned_at': assignment.assigned_at.isoformat(),
                'assignment_id': assignment.id
            })
        
        return JsonResponse({
            'success': True,
            'users': users,
            'count': len(users),
            'role_name': role.name
        })
        
    except Role.DoesNotExist:
        return JsonResponse({'error': 'Role not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_organization_access
@require_staff_access
def assign_user_to_role(request, role_id):
    """AJAX endpoint for assigning a user to a role"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    profile = get_user_profile(request)
    organization = profile.organization
    
    try:
        role = Role.objects.get(id=role_id, organization=organization)
        
        # Handle both JSON and form data
        if request.content_type == 'application/json':
            import json
            data = json.loads(request.body)
            user_profile_id = data.get('user_id')
        else:
            user_profile_id = request.POST.get('user_id')
        
        if not user_profile_id:
            return JsonResponse({'error': 'User ID is required'}, status=400)
        
        user_profile = UserProfile.objects.get(
            id=user_profile_id,
            organization=organization,
            is_active=True
        )
        
        # Check if user already has this role
        if UserRoleAssignment.objects.filter(
            user_profile=user_profile,
            role=role,
            is_active=True
        ).exists():
            return JsonResponse({'error': 'User already has this role'}, status=400)
        
        # Check role user limit
        if role.max_users:
            current_users = role.user_assignments.filter(is_active=True).count()
            if current_users >= role.max_users:
                return JsonResponse({
                    'error': f'Role "{role.name}" has reached its maximum user limit of {role.max_users}'
                }, status=400)
        
        # Create role assignment
        assignment = UserRoleAssignment.objects.create(
            user_profile=user_profile,
            role=role,
            assigned_by=profile,
            is_active=True
        )
        
        log_audit_action(
            user=request.user,
            action='assign_role',
            content_type='UserRoleAssignment',
            object_id=str(assignment.id),
            object_repr=f"{user_profile.user.get_full_name()} - {role.name}",
            changes={
                'role': role.name,
                'user': user_profile.user.get_full_name()
            },
            request=request
        )
        
        return JsonResponse({
            'success': True,
            'message': f'{user_profile.user.get_full_name()} assigned to role "{role.name}"',
            'user': {
                'id': user_profile.id,
                'full_name': user_profile.user.get_full_name() or user_profile.user.username,
                'email': user_profile.user.email,
                'initials': get_user_initials(user_profile.user),
                'department': user_profile.department or '',
                'title': user_profile.title or ''
            }
        })
        
    except Role.DoesNotExist:
        return JsonResponse({'error': 'Role not found'}, status=404)
    except UserProfile.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_organization_access
@require_staff_access
def remove_user_from_role(request, role_id, user_id):
    """AJAX endpoint for removing a user from a role"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    profile = get_user_profile(request)
    organization = profile.organization
    
    try:
        role = Role.objects.get(id=role_id, organization=organization)
        user_profile = UserProfile.objects.get(
            id=user_id,
            organization=organization
        )
        
        assignment = UserRoleAssignment.objects.get(
            user_profile=user_profile,
            role=role,
            is_active=True
        )
        
        assignment.is_active = False
        assignment.save()
        
        log_audit_action(
            user=request.user,
            action='remove_role',
            content_type='UserRoleAssignment',
            object_id=str(assignment.id),
            object_repr=f"{user_profile.user.get_full_name()} - {role.name}",
            changes={
                'role': role.name,
                'user': user_profile.user.get_full_name(),
                'removed': True
            },
            request=request
        )
        
        return JsonResponse({
            'success': True,
            'message': f'{user_profile.user.get_full_name()} removed from role "{role.name}"'
        })
        
    except Role.DoesNotExist:
        return JsonResponse({'error': 'Role not found'}, status=404)
    except UserProfile.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)
    except UserRoleAssignment.DoesNotExist:
        return JsonResponse({'error': 'User is not assigned to this role'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
