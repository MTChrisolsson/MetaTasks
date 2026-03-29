from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from core.models import AuditLog, UserProfile
from core.permissions import UserRoleAssignment

SUPPORT_GROUP_NAMES = {'customer_support', 'support_agent', 'support_admin'}


def _activity_icon(action):
    icon_map = {
        'create': 'fa-plus-circle',
        'update': 'fa-edit',
        'delete': 'fa-trash-alt',
        'login': 'fa-sign-in-alt',
        'logout': 'fa-sign-out-alt',
        'permission_granted': 'fa-user-shield',
        'permission_revoked': 'fa-user-minus',
        'export': 'fa-file-export',
        'import': 'fa-file-import',
    }
    return icon_map.get(action, 'fa-history')


def _log_support_audit(user, action, content_type, object_id='', object_repr='', changes=None, request=None):
    audit_data = {
        'user': user,
        'action': action,
        'content_type': content_type,
        'object_id': str(object_id) if object_id else '',
        'object_repr': object_repr or '',
        'changes': changes or {},
    }
    if request:
        audit_data.update(
            {
                'ip_address': request.META.get('REMOTE_ADDR'),
                'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200],
            }
        )
    AuditLog.objects.create(**audit_data)


def _has_customer_support_access(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name__in=SUPPORT_GROUP_NAMES).exists()


def require_customer_support_access(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not _has_customer_support_access(request.user):
            messages.error(request, 'You do not have access to the customer support portal.')
            return redirect('dashboard:dashboard')
        return view_func(request, *args, **kwargs)

    return wrapper


@login_required
@require_customer_support_access
def portal_dashboard(request):
    members = UserProfile.objects.select_related('user', 'organization')

    context = {
        'total_accounts': members.count(),
        'active_accounts': members.filter(user__is_active=True).count(),
        'inactive_accounts': members.filter(user__is_active=False).count(),
        'recent_activity_count': AuditLog.objects.count(),
    }
    return render(request, 'customer_support/dashboard.html', context)


@login_required
@require_customer_support_access
def account_management(request):
    search_query = (request.GET.get('search', '') or '').strip()
    status_filter = (request.GET.get('status', '') or '').strip()
    org_filter = (request.GET.get('org', '') or '').strip()

    users_query = UserProfile.objects.select_related('user', 'organization')

    if search_query:
        users_query = users_query.filter(
            Q(user__first_name__icontains=search_query)
            | Q(user__last_name__icontains=search_query)
            | Q(user__username__icontains=search_query)
            | Q(user__email__icontains=search_query)
            | Q(department__icontains=search_query)
            | Q(location__icontains=search_query)
            | Q(organization__name__icontains=search_query)
        )

    if status_filter == 'active':
        users_query = users_query.filter(user__is_active=True)
    elif status_filter == 'inactive':
        users_query = users_query.filter(user__is_active=False)

    if org_filter:
        users_query = users_query.filter(organization__id=org_filter)

    users_query = users_query.order_by('organization__name', 'user__last_name', 'user__first_name')

    paginator = Paginator(users_query, 25)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    account_rows = []
    for user_profile in page_obj:
        role_assignments = UserRoleAssignment.objects.filter(
            user_profile=user_profile,
            is_active=True,
        ).select_related('role')
        account_rows.append(
            {
                'id': user_profile.id,
                'user': user_profile.user,
                'profile': user_profile,
                'organization': user_profile.organization,
                'roles': [assignment.role for assignment in role_assignments],
            }
        )

    organizations = (
        UserProfile.objects.exclude(organization__isnull=True)
        .values('organization__id', 'organization__name')
        .distinct()
        .order_by('organization__name')
    )

    context = {
        'accounts': account_rows,
        'search_query': search_query,
        'status_filter': status_filter,
        'org_filter': org_filter,
        'organizations': organizations,
        'page_obj': page_obj,
    }
    return render(request, 'customer_support/account_management.html', context)


@login_required
@require_customer_support_access
def account_detail(request, user_id):
    user_profile = get_object_or_404(UserProfile.objects.select_related('user', 'organization'), id=user_id)

    role_assignments = UserRoleAssignment.objects.filter(
        user_profile=user_profile,
        is_active=True,
    ).select_related('role').order_by('-assigned_at')

    activity_items = []
    user_logs = AuditLog.objects.filter(user=user_profile.user).order_by('-timestamp')[:20]
    for log in user_logs:
        activity_items.append(
            {
                'action': log.action,
                'icon': _activity_icon(log.action),
                'description': f"{log.get_action_display()} {log.content_type} {log.object_repr}",
                'timestamp': log.timestamp,
            }
        )

    context = {
        'user_profile': user_profile,
        'role_assignments': role_assignments,
        'activity_items': activity_items,
        'can_edit': request.user.is_superuser or request.user.is_staff,
    }
    return render(request, 'customer_support/account_detail.html', context)


@login_required
@require_customer_support_access
def toggle_account_status(request, user_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({'error': 'Only support admins can change account status.'}, status=403)

    user_profile = get_object_or_404(UserProfile.objects.select_related('user'), id=user_id)
    old_status = user_profile.user.is_active
    user_profile.user.is_active = not old_status
    user_profile.user.save(update_fields=['is_active'])

    _log_support_audit(
        user=request.user,
        action='update',
        content_type='UserProfile',
        object_id=user_profile.id,
        object_repr=user_profile.user.get_full_name() or user_profile.user.username,
        changes={'is_active': {'old': old_status, 'new': user_profile.user.is_active}},
        request=request,
    )

    return JsonResponse(
        {
            'success': True,
            'new_status': 'Active' if user_profile.user.is_active else 'Inactive',
            'message': (
                f"{user_profile.user.get_full_name() or user_profile.user.username} "
                f"has been {'activated' if user_profile.user.is_active else 'deactivated'}."
            ),
        }
    )
