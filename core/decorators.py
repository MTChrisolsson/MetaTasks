"""
Permission decorators for view protection in RBAC system
"""

from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.urls import reverse
from typing import Union, List, Callable, Any
from core.services.permission_service import PermissionService


def require_permission(permission_codename: str, resource_param: str = None, 
                      resource_class=None, raise_404: bool = False, ajax_response: bool = False):
    """
    Decorator to require specific permission for view access
    
    Args:
        permission_codename: The permission code required (e.g., 'workflow.create')
        resource_param: URL parameter name for resource (e.g., 'workflow_id')
        resource_class: Model class for resource-scoped permissions
        raise_404: If True, raise 404 instead of 403 for better security
        ajax_response: If True, return JSON response for AJAX requests
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped_view(request, *args, **kwargs):
            user_profile = getattr(request.user, 'mediap_profile', None)
            if not user_profile:
                if ajax_response:
                    return JsonResponse({
                        'success': False,
                        'error': 'User profile not found'
                    }, status=403)
                if raise_404:
                    raise Http404()
                messages.error(request, 'User profile not found')
                return redirect('core:dashboard')
            
            resource = None
            if resource_param and resource_class:
                # Get resource from URL parameters
                resource_id = kwargs.get(resource_param)
                if resource_id:
                    resource = get_object_or_404(resource_class, id=resource_id)
            
            # Check permission using permission service
            permission_service = PermissionService(user_profile.organization)
            if not permission_service.has_permission(user_profile, permission_codename, resource):
                error_message = permission_service.get_missing_permission_message(permission_codename)
                
                if ajax_response:
                    return JsonResponse({
                        'success': False,
                        'error': error_message
                    }, status=403)
                
                if raise_404:
                    raise Http404()
                
                messages.error(request, error_message)
                return redirect('core:dashboard')
            
            # Add resource to request for easy access in view
            if resource:
                request.resource = resource
                
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def require_any_permission(permission_codenames: List[str], resource_param: str = None,
                          resource_class=None, raise_404: bool = False):
    """
    Decorator to require ANY of the specified permissions for view access
    
    Args:
        permission_codenames: List of permission codes (user needs at least one)
        resource_param: URL parameter name for resource
        resource_class: Model class for resource-scoped permissions
        raise_404: If True, raise 404 instead of 403 for better security
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped_view(request, *args, **kwargs):
            user_profile = getattr(request.user, 'mediap_profile', None)
            if not user_profile:
                if raise_404:
                    raise Http404()
                raise PermissionDenied("User profile not found")
            
            resource = None
            if resource_param and resource_class:
                resource_id = kwargs.get(resource_param)
                if resource_id:
                    resource = get_object_or_404(resource_class, id=resource_id)
            
            # Check if user has any of the permissions
            has_permission = any(
                user_profile.has_permission(perm, resource) 
                for perm in permission_codenames
            )
            
            if not has_permission:
                if raise_404:
                    raise Http404()
                raise PermissionDenied(f"Permission denied. Required: {', '.join(permission_codenames)}")
            
            if resource:
                request.resource = resource
                
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def require_all_permissions(permission_codenames: List[str], resource_param: str = None,
                           resource_class=None, raise_404: bool = False):
    """
    Decorator to require ALL of the specified permissions for view access
    
    Args:
        permission_codenames: List of permission codes (user needs all of them)
        resource_param: URL parameter name for resource
        resource_class: Model class for resource-scoped permissions
        raise_404: If True, raise 404 instead of 403 for better security
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped_view(request, *args, **kwargs):
            user_profile = getattr(request.user, 'mediap_profile', None)
            if not user_profile:
                if raise_404:
                    raise Http404()
                raise PermissionDenied("User profile not found")
            
            resource = None
            if resource_param and resource_class:
                resource_id = kwargs.get(resource_param)
                if resource_id:
                    resource = get_object_or_404(resource_class, id=resource_id)
            
            # Check if user has all permissions
            missing_permissions = [
                perm for perm in permission_codenames
                if not user_profile.has_permission(perm, resource)
            ]
            
            if missing_permissions:
                if raise_404:
                    raise Http404()
                raise PermissionDenied(f"Missing permissions: {', '.join(missing_permissions)}")
            
            if resource:
                request.resource = resource
                
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def require_organization_access(view_func):
    """
    Decorator to ensure user has access to their organization
    """
    @wraps(view_func)
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        user_profile = getattr(request.user, 'mediap_profile', None)
        if not user_profile:
            raise PermissionDenied("User profile not found")
        
        organization = user_profile.organization
        if not organization:
            raise PermissionDenied("User is not associated with any organization")
        
        # Add organization to request for easy access
        request.organization = organization
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def require_organization_admin(view_func):
    """
    Decorator to require organization admin privileges
    """
    @wraps(view_func)
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        user_profile = getattr(request.user, 'mediap_profile', None)
        if not user_profile:
            raise PermissionDenied("User profile not found")
        
        if not user_profile.is_organization_admin:
            raise PermissionDenied("Organization admin privileges required")
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def require_role_management(view_func):
    """
    Decorator to require role management permissions
    """
    @wraps(view_func)
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        user_profile = getattr(request.user, 'mediap_profile', None)
        if not user_profile:
            raise PermissionDenied("User profile not found")
        
        if not user_profile.can_manage_roles():
            raise PermissionDenied("Role management privileges required")
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


class PermissionMixin:
    """
    Mixin for class-based views to add permission checking
    """
    required_permission = None
    required_permissions = None  # List for any/all permission checks
    permission_check_type = 'any'  # 'any' or 'all'
    resource_param = None
    resource_class = None
    raise_404_on_deny = False
    
    def dispatch(self, request, *args, **kwargs):
        """Override dispatch to check permissions before view execution"""
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        
        user_profile = getattr(request.user, 'mediap_profile', None)
        if not user_profile:
            return self.handle_no_permission()
        
        # Get resource if specified
        resource = None
        if self.resource_param and self.resource_class:
            resource_id = kwargs.get(self.resource_param)
            if resource_id:
                try:
                    resource = get_object_or_404(self.resource_class, id=resource_id)
                    request.resource = resource
                except Http404:
                    if self.raise_404_on_deny:
                        raise
                    return self.handle_no_permission()
        
        # Check permissions
        if self.required_permission:
            if not user_profile.has_permission(self.required_permission, resource):
                return self.handle_no_permission()
        
        elif self.required_permissions:
            if self.permission_check_type == 'all':
                missing_perms = [
                    perm for perm in self.required_permissions
                    if not user_profile.has_permission(perm, resource)
                ]
                if missing_perms:
                    return self.handle_no_permission()
            else:  # 'any'
                has_any = any(
                    user_profile.has_permission(perm, resource)
                    for perm in self.required_permissions
                )
                if not has_any:
                    return self.handle_no_permission()
        
        return super().dispatch(request, *args, **kwargs)
    
    def handle_no_permission(self):
        """Handle permission denied - override in subclass for custom behavior"""
        if self.raise_404_on_deny:
            raise Http404()
        raise PermissionDenied("Permission denied")


# Convenience functions for template use
def user_has_permission(user, permission_codename: str, resource=None) -> bool:
    """
    Template-friendly function to check user permissions
    Usage in template: {% if user|user_has_permission:'workflow.create' %}
    """
    if not hasattr(user, 'mediap_profile'):
        return False
    return user.mediap_profile.has_permission(permission_codename, resource)


def user_has_any_permission(user, permission_codenames: List[str], resource=None) -> bool:
    """
    Check if user has any of the specified permissions
    """
    if not hasattr(user, 'mediap_profile'):
        return False
    return any(
        user.mediap_profile.has_permission(perm, resource) 
        for perm in permission_codenames
    )
