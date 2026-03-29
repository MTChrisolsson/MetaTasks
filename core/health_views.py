from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.contrib import messages
from core.models import Team
from services.cflows.models import TeamBooking


@login_required
def system_health_check(request):
    """System health check dashboard for administrators"""
    profile = getattr(request.user, 'mediap_profile', None)
    if not (request.user.is_superuser or (profile and (profile.is_organization_admin or profile.has_staff_panel_access))):
        messages.error(request, 'You do not have permission to access the health dashboard.')
        return redirect('dashboard:dashboard')
    
    # Check for teams with bookings but no active members
    problematic_teams = Team.objects.annotate(
        booking_count=Count('cflows_bookings'),
        active_member_count=Count('members', filter=Q(members__is_active=True))
    ).filter(
        booking_count__gt=0,
        active_member_count=0
    )
    
    # Check for teams with no members at all (regardless of bookings)
    empty_teams = Team.objects.annotate(
        member_count=Count('members')
    ).filter(member_count=0, is_active=True)
    
    # Check for bookings with inactive teams
    inactive_team_bookings = TeamBooking.objects.filter(
        team__is_active=False
    ).count()
    
    # Get summary statistics
    total_teams = Team.objects.filter(is_active=True).count()
    total_bookings = TeamBooking.objects.count()
    teams_with_bookings = Team.objects.filter(cflows_bookings__isnull=False).distinct().count()
    
    context = {
        'problematic_teams': problematic_teams,
        'empty_teams': empty_teams,
        'inactive_team_bookings': inactive_team_bookings,
        'total_teams': total_teams,
        'total_bookings': total_bookings,
        'teams_with_bookings': teams_with_bookings,
        'health_issues': problematic_teams.count() + empty_teams.count() + (1 if inactive_team_bookings > 0 else 0),
    }
    
    # Add health status message
    if context['health_issues'] == 0:
        messages.success(request, "System health check passed - no issues detected!")
    else:
        messages.warning(request, f"Found {context['health_issues']} potential issues that need attention.")
    
    return render(request, 'admin/system_health_check.html', context)