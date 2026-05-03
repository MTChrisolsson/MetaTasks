"""
Licensing management views for customer support and organization administrators
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.contrib.auth import get_user_model

from core.models import Organization, UserProfile
from .models import (
    Service, License, CustomLicense, UserLicenseAssignment, 
    LicenseAuditLog, LicenseType
)
from .services import LicensingService

User = get_user_model()


def is_customer_support(user):
    """Check if user is customer support or superuser"""
    return user.is_superuser or (
        hasattr(user, 'mediap_profile') and 
        user.mediap_profile.has_staff_panel_access
    )


@login_required
@user_passes_test(is_customer_support)
def license_dashboard(request):
    """Customer support dashboard for license management"""
    # Get statistics
    stats = {
        'total_organizations': Organization.objects.filter(is_active=True).count(),
        'total_custom_licenses': CustomLicense.objects.filter(is_active=True).count(),
        'total_assigned_users': UserLicenseAssignment.objects.filter(is_active=True).count(),
        'services': Service.objects.filter(is_active=True).count(),
    }
    
    # Actionable metrics for Support
    now = timezone.now()
    upcoming_expiry = License.objects.filter(
        status='active', 
        end_date__range=[now, now + timezone.timedelta(days=30)]
    ).select_related('organization', 'license_type__service')

    # Recent activity
    recent_logs = LicenseAuditLog.objects.select_related(
        'performed_by', 'affected_user__user', 'license__organization', 
        'custom_license__organization'
    ).order_by('-timestamp')[:20]
    
    # Organizations with most licenses
    top_organizations = Organization.objects.annotate(
        license_count=Count('custom_licenses')
    ).filter(
        license_count__gt=0
    ).order_by('-license_count')[:10]
    
    context = {
        'stats': stats,
        'recent_logs': recent_logs,
        'top_organizations': top_organizations,
        'upcoming_expiry': upcoming_expiry,
    }
    
    return render(request, 'licensing/dashboard.html', context)


@login_required
@user_passes_test(is_customer_support)
def organization_licenses(request, org_id=None):
    """View and manage licenses for organizations"""
    if org_id:
        organization = get_object_or_404(Organization, id=org_id)
        organizations = [organization]
    else:
        # List all organizations with pagination
        search_query = request.GET.get('search', '')
        organizations_qs = Organization.objects.prefetch_related('members__user').all().order_by('-created_at')
        
        if search_query:
            organizations_qs = organizations_qs.filter(
                Q(name__icontains=search_query) | 
                Q(description__icontains=search_query) |
                Q(slug__icontains=search_query) |
                Q(members__user__email__icontains=search_query) |
                Q(members__user__username__icontains=search_query)
            ).distinct()
        
        paginator = Paginator(organizations_qs, 20)
        page_number = request.GET.get('page')
        organizations = paginator.get_page(page_number)
    
    # Get license summary for each organization
    org_summaries = []
    for org in organizations:
        summary = LicensingService.get_organization_license_summary(org)
        org_summaries.append({
            'organization': org,
            'summary': summary
        })
    
    context = {
        'organizations': organizations,
        'org_summaries': org_summaries,
        'search_query': request.GET.get('search', ''),
        'single_org': org_id is not None,
        'services': Service.objects.filter(is_active=True).order_by('name'),
    }
    
    return render(request, 'licensing/organization_licenses.html', context)


@login_required
@user_passes_test(is_customer_support)
def create_custom_license(request):
    """Create a new custom license"""
    if request.method == 'POST':
        try:
            organization = get_object_or_404(Organization, id=request.POST.get('organization_id'))
            service = get_object_or_404(Service, id=request.POST.get('service_id'))
            
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
            return redirect('licensing:organization_licenses', org_id=organization.id)
            
        except Exception as e:
            messages.error(request, f'Error creating custom license: {str(e)}')
    
    # GET request - show form
    organizations = Organization.objects.filter(is_active=True).order_by('name')
    services = Service.objects.filter(is_active=True).order_by('name')
    
    context = {
        'organizations': organizations,
        'services': services,
    }
    
    return render(request, 'licensing/create_custom_license.html', context)


@login_required
def organization_license_management(request):
    """Organization admin view for managing their own licenses"""
    try:
        user_profile = request.user.mediap_profile
        organization = user_profile.organization
    except:
        messages.error(request, 'No organization profile found.')
        return redirect('dashboard:dashboard')
    
    # Check if user is organization admin
    if not (user_profile.is_organization_admin or user_profile.has_staff_panel_access):
        messages.error(request, 'You do not have permission to manage licenses.')
        return redirect('dashboard:dashboard')
    
    # Handle user assignment/revocation
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'assign_user':
            license_id = request.POST.get('license_id')
            user_profile_id = request.POST.get('user_profile_id')
            
            try:
                license = License.objects.get(id=license_id, organization=organization)
                target_user_profile = UserProfile.objects.get(
                    id=user_profile_id, 
                    organization=organization
                )
                
                success, result = LicensingService.assign_user_to_license(
                    license, target_user_profile, request.user
                )
                
                if success:
                    messages.success(request, f'License assigned to {target_user_profile.user.get_full_name()}.')
                else:
                    messages.error(request, result)
                    
            except (License.DoesNotExist, UserProfile.DoesNotExist):
                messages.error(request, 'Invalid license or user.')
                
        elif action == 'revoke_user':
            assignment_id = request.POST.get('assignment_id')
            
            try:
                assignment = UserLicenseAssignment.objects.get(
                    id=assignment_id,
                    license__organization=organization,
                    is_active=True
                )
                
                success, result = LicensingService.revoke_user_license(
                    assignment, request.user, request.POST.get('reason', '')
                )
                
                if success:
                    messages.success(request, f'License revoked from {assignment.user_profile.user.get_full_name()}.')
                else:
                    messages.error(request, result)
                    
            except UserLicenseAssignment.DoesNotExist:
                messages.error(request, 'Invalid license assignment.')
        
        return redirect('licensing:organization_management')
    
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
    ).select_related('user_profile__user', 'license__license_type__service', 'license__custom_license__service')
    
    context = {
        'organization': organization,
        'summary': summary,
        'organization_members': organization_members,
        'current_assignments': current_assignments,
    }
    
    return render(request, 'licensing/organization_management.html', context)


@login_required
@require_http_methods(["GET"])
def check_user_access(request, service_slug):
    """AJAX endpoint to check if user has access to a service"""
    try:
        user_profile = request.user.mediap_profile
        has_access = LicensingService.has_service_access(user_profile, service_slug)
        
        return JsonResponse({
            'has_access': has_access,
            'service_slug': service_slug
        })
    except:
        return JsonResponse({
            'has_access': False,
            'error': 'No user profile found'
        })


@login_required
def service_access_denied(request, service_slug):
    """Show access denied page for unlicensed services"""
    try:
        service = Service.objects.get(slug=service_slug, is_active=True)
        user_profile = request.user.mediap_profile
        organization = user_profile.organization
        
        # Get available licenses for this service
        available_licenses = LicensingService.get_available_licenses_for_user(
            organization, service
        )
        
        context = {
            'service': service,
            'organization': organization,
            'available_licenses': available_licenses,
            'is_org_admin': user_profile.is_organization_admin,
        }
        
        return render(request, 'licensing/access_denied.html', context)
        
    except (Service.DoesNotExist, AttributeError):
        messages.error(request, 'Service not found or no organization profile.')
        return redirect('dashboard:dashboard')
