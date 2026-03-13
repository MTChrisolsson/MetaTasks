from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta
from licensing.models import Service, License
from .models import Organization, UserProfile, Team, CalendarEvent


@login_required
def dashboard(request):
    """
    Main dashboard for logged-in users showing overview of their MetaTask experience
    """
    try:
        profile = request.user.mediap_profile
    except (UserProfile.DoesNotExist, AttributeError):
        # User doesn't have a profile yet, redirect to setup
        return render(request, 'core/dashboard_no_profile.html')
    
    if not profile.organization:
        # User needs to create or join an organization
        return render(request, 'core/dashboard_no_organization.html')
    
    organization = profile.organization
    
    # Get all services
    available_services = Service.objects.filter(is_active=True).order_by('sort_order', 'name')
    
    # Get user's licenses through their organization
    licenses = License.objects.filter(
        organization=organization,
        status__in=['active', 'trial']
    ).select_related('license_type', 'license_type__service')
    
    # Build service access map
    licensed_services = {}
    for license in licenses:
        service = license.license_type.service
        licensed_services[service.slug] = {
            'service': service,
            'license': license,
            'usage': {
                'users': license.usage_percentage('users'),
                'workflows': license.usage_percentage('workflows'),
                'projects': license.usage_percentage('projects'),
                'storage_gb': license.usage_percentage('storage_gb'),
            }
        }
    
    # Get user's team memberships
    user_teams = profile.teams.filter(is_active=True)
    
    # Get recent calendar events
    recent_events = CalendarEvent.objects.filter(
        organization=organization,
        start_time__gte=timezone.now() - timedelta(days=30)
    ).order_by('-start_time')[:5]
    
    # Get upcoming events
    upcoming_events = CalendarEvent.objects.filter(
        organization=organization,
        start_time__gte=timezone.now()
    ).order_by('start_time')[:5]
    
    # Organization statistics
    org_stats = {
        'total_users': organization.members.count(),
        'active_teams': organization.teams.filter(is_active=True).count(),
        'total_events': CalendarEvent.objects.filter(organization=organization).count(),
        'events_this_month': CalendarEvent.objects.filter(
            organization=organization,
            start_time__gte=timezone.now().replace(day=1)
        ).count(),
    }
    
    # Check if user is organization admin
    is_org_admin = profile.is_organization_admin
    
    # Get CFlows-specific stats if they have access
    cflows_stats = None
    if 'cflows' in licensed_services:
        try:
            from services.cflows.models import WorkItem, Workflow
            cflows_stats = {
                'total_workflows': Workflow.objects.filter(organization=organization, is_active=True).count(),
                'active_work_items': WorkItem.objects.filter(
                    workflow__organization=organization,
                    is_completed=False
                ).count(),
                'my_assigned_items': WorkItem.objects.filter(
                    workflow__organization=organization,
                    current_assignee=profile,
                    is_completed=False
                ).count(),
            }
        except ImportError:
            # CFlows models not available
            pass
    
    # Build quick actions based on user's permissions and services
    quick_actions = []
    
    # Add service-specific actions
    if 'cflows' in licensed_services and profile.has_staff_panel_access:
        quick_actions.extend([
            {
                'title': 'Create Workflow',
                'description': 'Set up a new workflow process',
                'url': '/services/cflows/workflows/create/',
                'icon': 'fas fa-plus-circle',
                'color': 'blue'
            },
            {
                'title': 'View My Work Items',
                'description': 'Check assigned tasks',
                'url': '/services/cflows/my-items/',
                'icon': 'fas fa-tasks',
                'color': 'green'
            }
        ])
    
    # Admin actions
    if is_org_admin:
        quick_actions.extend([
            {
                'title': 'Manage Team',
                'description': 'Add or remove team members',
                'url': '/core/organization/members/',
                'icon': 'fas fa-users',
                'color': 'purple'
            },
            {
                'title': 'Organization Settings',
                'description': 'Update organization details',
                'url': '/core/organization/settings/',
                'icon': 'fas fa-cog',
                'color': 'gray'
            }
        ])
    
    # Calendar action
    quick_actions.append({
        'title': 'Schedule Event',
        'description': 'Create a new calendar event',
        'url': '/core/calendar/create/',
        'icon': 'fas fa-calendar-plus',
        'color': 'indigo'
    })
    
    context = {
        'profile': profile,
        'organization': organization,
        'org_stats': org_stats,
        'available_services': available_services,
        'licensed_services': licensed_services,
        'user_teams': user_teams,
        'recent_events': recent_events,
        'upcoming_events': upcoming_events,
        'cflows_stats': cflows_stats,
        'is_org_admin': is_org_admin,
        'quick_actions': quick_actions,
        'licenses': licenses,
    }
    
    return render(request, 'core/dashboard.html', context)


@login_required
def service_access_check(request, service_slug):
    """
    Check if user has access to a specific service and redirect appropriately
    """
    try:
        profile = request.user.mediap_profile
        if not profile.organization:
            return render(request, 'core/dashboard_no_organization.html')
        
        # Check if they have a license for this service
        service = Service.objects.get(slug=service_slug, is_active=True)
        license = License.objects.filter(
            organization=profile.organization,
            license_type__service=service,
            status__in=['active', 'trial']
        ).first()
        
        if not license:
            return render(request, 'core/no_service_access.html', {
                'service': service,
                'organization': profile.organization
            })
        
        # Redirect to the service
        if service_slug == 'cflows':
            return redirect('/services/cflows/')
        elif service_slug == 'scheduling':
            return redirect('/services/scheduling/')
        elif service_slug == 'analytics':
            return redirect('/services/analytics/')
        elif service_slug == 'job-planning':
            return redirect('/services/job-planning/')
        elif service_slug == 'dashboard':
            return redirect('/services/dashboard/')
        else:
            return render(request, 'core/service_coming_soon.html', {'service': service})
            
    except (UserProfile.DoesNotExist, Service.DoesNotExist):
        return render(request, 'core/dashboard_no_profile.html')
