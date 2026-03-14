"""
Views for organizational role and user management
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.contrib.auth import get_user_model
from core.models import UserProfile, Organization, Team
from core.permissions import Role, UserRoleAssignment
from core.views import require_organization_access
from core.decorators import require_permission
from accounts.forms import UserCreationForm


User = get_user_model()


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
@require_permission('user.view')
def user_management(request):
    """User management dashboard for HR managers"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'core/no_profile.html')
    
    # Check if user can manage users
    can_manage_users = (
        profile.is_organization_admin or 
        profile.has_role_permission('user.create') or
        profile.has_role_permission('user.edit')
    )
    
    if not can_manage_users:
        messages.error(request, 'You do not have permission to manage users.')
        return redirect('core:dashboard')
    
    # Get manageable locations
    manageable_locations = profile.get_manageable_locations()
    
    # Get users in manageable locations
    if profile.is_organization_admin:
        users = UserProfile.objects.filter(
            organization=profile.organization,
            is_active=True
        ).select_related('user').order_by('user__last_name', 'user__first_name')
    else:
        users = UserProfile.objects.filter(
            organization=profile.organization,
            is_active=True,
            location__in=manageable_locations
        ).select_related('user').order_by('user__last_name', 'user__first_name')
    
    context = {
        'profile': profile,
        'users': users,
        'manageable_locations': manageable_locations,
        'can_create_users': profile.has_role_permission('user.create'),
        'can_edit_users': profile.has_role_permission('user.edit'),
        'can_assign_roles': profile.has_role_permission('user.assign_roles'),
    }
    
    return render(request, 'core/user_management.html', context)


@login_required
@require_organization_access
def create_user(request):
    """Create a new user (HR managers can create users in their locations)"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'core/no_profile.html')
    
    # Check permissions
    if not profile.has_role_permission('user.create') and not profile.is_organization_admin:
        messages.error(request, 'You do not have permission to create users.')
        return redirect('core:user_management')
    
    manageable_locations = profile.get_manageable_locations()
    
    if request.method == 'POST':
        # Create custom form data
        form_data = request.POST.copy()
        location = form_data.get('location', '')
        
        # Check if user can create users in this location
        if not profile.is_organization_admin and location not in manageable_locations:
            messages.error(request, f'You do not have permission to create users in {location}.')
            return redirect('core:create_user')
        
        # Create the user
        try:
            with transaction.atomic():
                # Create User
                raw_username = (form_data.get('username') or '').strip()
                normalized_username = raw_username.lower()

                if User.objects.filter(username__iexact=raw_username).exists():
                    raise ValueError('A user with that username already exists.')


                user = User.objects.create_user(
                    username=normalized_username,
                    display_username=raw_username,
                    email=form_data['email'],
                    first_name=form_data['first_name'],
                    last_name=form_data['last_name'],
                    password=form_data['password1']
                )
                
                # Create UserProfile
                user_profile = UserProfile.objects.create(
                    user=user,
                    organization=profile.organization,
                    title=form_data.get('title', ''),
                    department=form_data.get('department', ''),
                    location=location,
                    phone=form_data.get('phone', ''),
                    mobile=form_data.get('mobile', ''),
                )
                
                # Assign default role
                default_role = Role.objects.filter(
                    organization=profile.organization,
                    is_default=True
                ).first()
                
                if default_role:
                    UserRoleAssignment.objects.create(
                        user_profile=user_profile,
                        role=default_role,
                        assigned_by=profile
                    )
                
                messages.success(request, f'User {user.get_full_name()} created successfully!')
                return redirect('core:user_management')
                
        except Exception as e:
            messages.error(request, f'Error creating user: {str(e)}')
    
    # Get available roles for assignment
    available_roles = Role.objects.filter(
        organization=profile.organization,
        is_active=True
    ).order_by('name')
    
    context = {
        'profile': profile,
        'manageable_locations': manageable_locations,
        'available_roles': available_roles,
    }
    
    return render(request, 'core/create_user.html', context)


@login_required
@require_organization_access
def assign_role(request, user_id):
    """Assign a role to a user with location context"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'core/no_profile.html')
    
    target_user = get_object_or_404(
        UserProfile, 
        id=user_id, 
        organization=profile.organization
    )
    
    # Check permissions
    if not profile.has_role_permission('user.assign_roles') and not profile.is_organization_admin:
        messages.error(request, 'You do not have permission to assign roles.')
        return redirect('core:user_management')
    
    # Check if user can manage this target user
    if not profile.can_manage_user_in_location(target_user, target_user.location):
        messages.error(request, 'You do not have permission to manage this user.')
        return redirect('core:user_management')
    
    if request.method == 'POST':
        role_id = request.POST.get('role')
        location = request.POST.get('location', '')
        
        try:
            role = Role.objects.get(
                id=role_id,
                organization=profile.organization
            )
            
            # Create role assignment with location context
            assignment, created = UserRoleAssignment.objects.get_or_create(
                user_profile=target_user,
                role=role,
                defaults={
                    'assigned_by': profile,
                    'conditions': {'location': location} if location else {}
                }
            )
            
            if created:
                messages.success(request, f'Role {role.name} assigned to {target_user.user.get_full_name()}')
            else:
                messages.info(request, f'{target_user.user.get_full_name()} already has the {role.name} role')
            
        except Role.DoesNotExist:
            messages.error(request, 'Invalid role selected.')
        except Exception as e:
            messages.error(request, f'Error assigning role: {str(e)}')
    
    return redirect('core:user_management')


@login_required
@require_organization_access
def get_user_locations(request):
    """API endpoint to get locations for user management"""
    profile = get_user_profile(request)
    if not profile:
        return JsonResponse({'error': 'No profile found'}, status=404)
    
    locations = profile.get_manageable_locations()
    return JsonResponse({'locations': locations})


@login_required
@require_organization_access
def role_management(request):
    """Role management dashboard"""
    profile = get_user_profile(request)
    if not profile:
        return render(request, 'core/no_profile.html')
    
    if not profile.is_organization_admin:
        messages.error(request, 'Only organization administrators can manage roles.')
        return redirect('core:dashboard')
    
    roles = Role.objects.filter(
        organization=profile.organization
    ).order_by('name')
    
    context = {
        'profile': profile,
        'roles': roles,
    }
    
    return render(request, 'core/role_management.html', context)
