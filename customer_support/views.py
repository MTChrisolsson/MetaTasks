import csv
from datetime import datetime, time
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.models import AuditLog, Organization, UserProfile
from core.permissions import UserRoleAssignment

from .forms import (
    CustomerTicketCreateForm,
    KBArticleForm,
    SupportSearchForm,
    SupportTicketCommentForm,
    SupportTicketForm,
    SupportTicketUpdateForm,
)
from .models import KBArticle, KBCategory, SupportTicket, SupportTicketAuditLog, SupportTicketComment, TicketRelationship
from .ws_events import broadcast_ticket_event

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
    return get_user_support_tier(user) in {'superuser', 'staff', 'support_agent'}


def get_user_support_tier(user):
    """Return support tier: 'superuser', 'staff', 'support_agent', 'customer', 'none'."""
    if not user.is_authenticated:
        return 'none'
    if user.is_superuser:
        return 'superuser'
    if user.is_staff or user.groups.filter(name='support_admin').exists():
        return 'staff'
    if user.groups.filter(name='support_agent').exists() or user.groups.filter(name='customer_support').exists():
        return 'support_agent'
    if hasattr(user, 'mediap_profile'):
        return 'customer'
    return 'none'


def require_customer_support_access(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not _has_customer_support_access(request.user):
            messages.error(request, 'You do not have access to the customer support portal.')
            return redirect('dashboard:dashboard')
        return view_func(request, *args, **kwargs)

    return wrapper


def require_support_staff_access(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        tier = get_user_support_tier(request.user)
        if tier not in {'superuser', 'staff', 'support_agent'}:
            messages.error(request, 'Support staff access is required.')
            return redirect('customer_support:dashboard')
        return view_func(request, *args, **kwargs)

    return wrapper


def require_support_admin_access(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        tier = get_user_support_tier(request.user)
        if tier not in {'superuser', 'staff'}:
            messages.error(request, 'Support admin access is required.')
            return redirect('customer_support:dashboard')
        return view_func(request, *args, **kwargs)

    return wrapper


def _support_license_seat_limit(license_obj):
    """Resolve seat limit across standard/custom license definitions."""
    if getattr(license_obj, 'custom_license', None) and license_obj.custom_license.max_users:
        return license_obj.custom_license.max_users

    max_users = license_obj.license_type.max_users
    if max_users:
        return max_users

    features = license_obj.license_type.features
    if isinstance(features, dict):
        agents = features.get('agents')
        if isinstance(agents, int):
            return agents
    return None


def _support_license_warnings(license_obj, assigned_count):
    """Return warning messages for support license visibility (non-blocking)."""
    warnings = []
    if license_obj.status not in {'active', 'trial'}:
        warnings.append(f'License status is {license_obj.status}.')

    seat_limit = _support_license_seat_limit(license_obj)
    if seat_limit:
        usage_pct = (assigned_count / seat_limit) * 100
        if usage_pct >= 80:
            warnings.append(f'Seat usage is {usage_pct:.0f}% ({assigned_count}/{seat_limit}).')

    if license_obj.end_date:
        days_left = (license_obj.end_date - timezone.now()).days
        if days_left < 0:
            warnings.append('License has expired.')
        elif days_left <= 14:
            warnings.append(f'License expires in {days_left} day(s).')

    return warnings


def require_customer_access(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        tier = get_user_support_tier(request.user)
        if tier not in {'superuser', 'staff', 'support_agent'}:
            messages.error(request, 'Support access is required.')
            return redirect('dashboard:dashboard')
        return view_func(request, *args, **kwargs)

    return wrapper


def _get_user_profile(user):
    return getattr(user, 'mediap_profile', None)


def _get_ticket_queryset(user):
    profile = _get_user_profile(user)
    queryset = SupportTicket.objects.select_related('organization', 'created_by', 'assigned_to').prefetch_related('tags')
    if profile:
        return queryset.filter(organization=profile.organization, is_archived=False)
    return queryset.none()


def _log_ticket_audit(ticket, action, user, old_value=None, new_value=None):
    SupportTicketAuditLog.objects.create(
        ticket=ticket,
        action=action,
        performed_by=user,
        old_value=old_value or {},
        new_value=new_value or {},
    )


@login_required
@require_customer_support_access
def portal_dashboard(request):
    members = UserProfile.objects.select_related('user', 'organization')
    tickets = _get_ticket_queryset(request.user)

    context = {
        'total_accounts': members.count(),
        'active_accounts': members.filter(user__is_active=True).count(),
        'inactive_accounts': members.filter(user__is_active=False).count(),
        'recent_activity_count': AuditLog.objects.count(),
        'open_ticket_count': tickets.filter(status='open').count(),
        'in_progress_ticket_count': tickets.filter(status='in_progress').count(),
        'awaiting_customer_count': tickets.filter(status='awaiting_customer').count(),
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
    return render(request, 'customer_support/accounts/management.html', context)


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

    from licensing.models import License
    support_licenses = License.objects.filter(
        organization=user_profile.organization,
        license_type__service__slug='customer_support',
    )
    active_support_licenses = support_licenses.filter(status__in=['active', 'trial'])
    context['support_license_context'] = {
        'has_support_license': support_licenses.exists(),
        'active_license_count': active_support_licenses.count(),
        'warning_count': max(0, support_licenses.count() - active_support_licenses.count()),
    }

    return render(request, 'customer_support/accounts/detail.html', context)


@login_required
@require_support_admin_access
def support_licensing_dashboard(request):
    from licensing.models import License, Service, UserLicenseAssignment

    search = (request.GET.get('search') or '').strip()
    orgs = Organization.objects.filter(is_active=True).order_by('name')
    if search:
        orgs = orgs.filter(Q(name__icontains=search) | Q(description__icontains=search))

    paginator = Paginator(orgs, 25)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    org_rows = []
    for org in page_obj:
        licenses = list(
            License.objects.filter(organization=org)
            .select_related('license_type__service', 'custom_license')
            .order_by('-created_at')
        )
        active_licenses = [lic for lic in licenses if lic.status in {'active', 'trial'}]
        service_count = len({lic.license_type.service_id for lic in licenses})

        total_capacity = 0
        has_unlimited = False
        total_assigned = 0
        for lic in active_licenses:
            assigned = UserLicenseAssignment.objects.filter(license=lic, is_active=True).count()
            total_assigned += assigned
            seat_limit = _support_license_seat_limit(lic)
            if seat_limit is None:
                has_unlimited = True
            else:
                total_capacity += seat_limit

        remaining_seats = None if has_unlimited else max(0, total_capacity - total_assigned)

        support_active_license = next(
            (lic for lic in active_licenses if lic.license_type.service.slug == 'customer_support'),
            None,
        )

        support_assigned_count = 0
        support_seat_limit = None
        warnings = []
        if support_active_license:
            support_assigned_count = UserLicenseAssignment.objects.filter(
                license=support_active_license,
                is_active=True,
            ).count()
            support_seat_limit = _support_license_seat_limit(support_active_license)
            warnings.extend(_support_license_warnings(support_active_license, support_assigned_count))

        if not licenses:
            warnings.append('No service licenses provisioned yet.')
        elif not active_licenses:
            warnings.append('No active service licenses.')

        org_rows.append(
            {
                'organization': org,
                'total_licenses': len(licenses),
                'service_count': service_count,
                'active_license_count': len(active_licenses),
                'total_assigned': total_assigned,
                'total_capacity': None if has_unlimited else total_capacity,
                'remaining_seats': remaining_seats,
                'support_assigned_count': support_assigned_count,
                'support_seat_limit': support_seat_limit,
                'warnings': warnings,
            }
        )

    context = {
        'search': search,
        'page_obj': page_obj,
        'org_rows': org_rows,
        'service_count': Service.objects.filter(is_active=True).count(),
    }
    return render(request, 'customer_support/licensing/dashboard.html', context)


@login_required
@require_support_admin_access
def support_licensing_organization_detail(request, org_id):
    from licensing.models import License, LicenseType, Service, UserLicenseAssignment
    from licensing.services import LicensingService

    organization = get_object_or_404(Organization, id=org_id, is_active=True)
    support_service = get_object_or_404(Service, slug='customer_support', is_active=True)

    all_org_licenses_qs = License.objects.filter(
        organization=organization,
    ).select_related('license_type__service', 'custom_license').order_by('license_type__service__name', '-created_at')

    support_licenses = License.objects.filter(
        organization=organization,
        license_type__service=support_service,
    ).select_related('license_type', 'custom_license').order_by('-created_at')

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        if action == 'provision_service_license':
            license_type = get_object_or_404(
                LicenseType.objects.select_related('service'),
                id=request.POST.get('license_type_id'),
                is_active=True,
                service__is_active=True,
            )

            status = (request.POST.get('status') or 'active').strip()
            billing_cycle = (request.POST.get('billing_cycle') or 'monthly').strip()
            try:
                duration_days = int(request.POST.get('duration_days') or 365)
            except ValueError:
                duration_days = 365

            start_date = timezone.now()
            expiration_date_raw = (request.POST.get('expiration_date') or '').strip()
            end_date = None
            if expiration_date_raw:
                try:
                    parsed_date = datetime.strptime(expiration_date_raw, '%Y-%m-%d').date()
                    end_date = timezone.make_aware(datetime.combine(parsed_date, time.max))
                except ValueError:
                    messages.error(request, 'Invalid expiration date. Use YYYY-MM-DD.')
                    return redirect('customer_support:support_licensing_organization_detail', org_id=organization.id)
            elif billing_cycle != 'lifetime' and duration_days > 0:
                end_date = start_date + timezone.timedelta(days=duration_days)

            license_obj, created = License.objects.get_or_create(
                organization=organization,
                license_type=license_type,
                defaults={
                    'account_type': 'organization',
                    'status': status,
                    'billing_cycle': billing_cycle,
                    'start_date': start_date,
                    'end_date': end_date,
                    'created_by': request.user,
                },
            )

            if not created:
                old_values = {
                    'status': license_obj.status,
                    'billing_cycle': license_obj.billing_cycle,
                    'end_date': license_obj.end_date.isoformat() if license_obj.end_date else None,
                }
                license_obj.status = status
                license_obj.billing_cycle = billing_cycle
                license_obj.start_date = start_date
                license_obj.end_date = end_date
                license_obj.save(update_fields=['status', 'billing_cycle', 'start_date', 'end_date', 'updated_at'])
                messages.success(request, f'Updated {license_type.service.name} - {license_type.display_name} for {organization.name}.')
                _log_support_audit(
                    user=request.user,
                    action='update',
                    content_type='License',
                    object_id=str(license_obj.id),
                    object_repr=f'{organization.name} / {license_type.service.slug}',
                    changes={
                        'service_license': {
                            'service': license_type.service.slug,
                            'license_type': license_type.display_name,
                            'old': old_values,
                            'new': {
                                'status': status,
                                'billing_cycle': billing_cycle,
                                'end_date': end_date.isoformat() if end_date else None,
                            },
                        }
                    },
                    request=request,
                )
            else:
                messages.success(request, f'Created {license_type.service.name} - {license_type.display_name} for {organization.name}.')
                _log_support_audit(
                    user=request.user,
                    action='create',
                    content_type='License',
                    object_id=str(license_obj.id),
                    object_repr=f'{organization.name} / {license_type.service.slug}',
                    changes={
                        'service_license': {
                            'service': license_type.service.slug,
                            'license_type': license_type.display_name,
                            'status': status,
                            'billing_cycle': billing_cycle,
                            'end_date': end_date.isoformat() if end_date else None,
                        }
                    },
                    request=request,
                )
            return redirect('customer_support:support_licensing_organization_detail', org_id=organization.id)

        if action == 'assign_seat':
            license_obj = get_object_or_404(all_org_licenses_qs, id=request.POST.get('license_id'), status__in=['active', 'trial'])
            target_profile = get_object_or_404(UserProfile, id=request.POST.get('user_profile_id'), organization=organization)
            success, result = LicensingService.assign_user_to_license(license_obj, target_profile, request.user)
            if success:
                messages.success(request, f'Seat assigned to {target_profile.user.get_full_name() or target_profile.user.username}.')
                _log_support_audit(
                    user=request.user,
                    action='update',
                    content_type='License',
                    object_id=str(license_obj.id),
                    object_repr=f'{organization.name} / {license_obj.license_type.service.slug}',
                    changes={
                        'seat_assignment': {
                            'user_profile_id': str(target_profile.id),
                            'service': license_obj.license_type.service.slug,
                            'assigned': True,
                        }
                    },
                    request=request,
                )
            else:
                messages.error(request, result)
            return redirect('customer_support:support_licensing_organization_detail', org_id=organization.id)

        if action == 'revoke_seat':
            assignment = get_object_or_404(
                UserLicenseAssignment.objects.select_related('user_profile__user', 'license__license_type__service'),
                id=request.POST.get('assignment_id'),
                license__organization=organization,
                is_active=True,
            )
            reason = (request.POST.get('reason') or '').strip()
            success, result = LicensingService.revoke_user_license(assignment, request.user, reason)
            if success:
                messages.success(request, f'Seat revoked from {assignment.user_profile.user.get_full_name() or assignment.user_profile.user.username}.')
                _log_support_audit(
                    user=request.user,
                    action='update',
                    content_type='License',
                    object_id=str(assignment.license.id),
                    object_repr=f'{organization.name} / {assignment.license.license_type.service.slug}',
                    changes={
                        'seat_assignment': {
                            'user_profile_id': str(assignment.user_profile.id),
                            'service': assignment.license.license_type.service.slug,
                            'revoked': True,
                        }
                    },
                    request=request,
                )
            else:
                messages.error(request, result)
            return redirect('customer_support:support_licensing_organization_detail', org_id=organization.id)

    assignments = UserLicenseAssignment.objects.filter(
        license__organization=organization,
        license__license_type__service=support_service,
        is_active=True,
    ).select_related('user_profile__user', 'license__license_type', 'license__custom_license').order_by('user_profile__user__first_name', 'user_profile__user__last_name')

    org_members = UserProfile.objects.filter(
        organization=organization,
        is_active=True,
        user__is_active=True,
    ).select_related('user').order_by('user__first_name', 'user__last_name', 'user__username')

    assignable_members = list(org_members)

    support_assignable_license_rows = []

    license_rows = []
    for license_obj in support_licenses:
        assigned_count = assignments.filter(license=license_obj).count()
        row = {
            'license': license_obj,
            'assigned_count': assigned_count,
            'seat_limit': _support_license_seat_limit(license_obj),
            'warnings': _support_license_warnings(license_obj, assigned_count),
        }
        license_rows.append(row)
        if license_obj.status in {'active', 'trial'}:
            support_assignable_license_rows.append(row)

    service_license_rows = []
    for license_obj in all_org_licenses_qs:
        assigned_count = assignments.filter(license=license_obj).count()
        seat_limit = _support_license_seat_limit(license_obj)
        remaining = None if seat_limit is None else max(0, seat_limit - assigned_count)
        service_license_rows.append(
            {
                'license': license_obj,
                'assigned_count': assigned_count,
                'seat_limit': seat_limit,
                'remaining_seats': remaining,
                'warnings': _support_license_warnings(license_obj, assigned_count),
            }
        )

    active_service_rows = [row for row in service_license_rows if row['license'].status in {'active', 'trial'}]
    has_unlimited = any(row['seat_limit'] is None for row in active_service_rows)
    total_assigned = sum(row['assigned_count'] for row in active_service_rows)
    total_capacity = None if has_unlimited else sum(row['seat_limit'] or 0 for row in active_service_rows)
    total_remaining = None if has_unlimited else max(0, (total_capacity or 0) - total_assigned)

    license_types = LicenseType.objects.filter(is_active=True, service__is_active=True).select_related('service').order_by('service__name', 'display_name')

    context = {
        'organization': organization,
        'license_rows': license_rows,
        'support_assignable_license_rows': support_assignable_license_rows,
        'assignments': assignments,
        'assignable_members': assignable_members,
        'service_license_rows': service_license_rows,
        'license_types': license_types,
        'status_choices': License.STATUS_CHOICES,
        'billing_choices': License.BILLING_CYCLE_CHOICES,
        'capacity_summary': {
            'active_license_count': len(active_service_rows),
            'total_assigned': total_assigned,
            'total_capacity': total_capacity,
            'total_remaining': total_remaining,
            'has_unlimited': has_unlimited,
        },
    }
    return render(request, 'customer_support/licensing/organization_detail.html', context)


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


@login_required
@require_support_staff_access
def ticket_dashboard(request):
    tickets = _get_ticket_queryset(request.user)
    now = timezone.now()
    context = {
        'total_tickets': tickets.count(),
        'open_tickets': tickets.filter(status='open').count(),
        'in_progress_tickets': tickets.filter(status='in_progress').count(),
        'awaiting_customer_tickets': tickets.filter(status='awaiting_customer').count(),
        'resolved_tickets': tickets.filter(status='resolved').count(),
        'closed_tickets': tickets.filter(status='closed').count(),
        'sla_risk_tickets': tickets.filter(sla_deadline__isnull=False, sla_deadline__lt=now).exclude(
            status__in=['resolved', 'closed']
        ).count(),
    }
    return render(request, 'customer_support/tickets/dashboard.html', context)


@login_required
@require_support_staff_access
def ticket_list(request):
    queryset = _get_ticket_queryset(request.user)
    form = SupportSearchForm(request.GET or None)

    search_query = ''
    status_filter = ''
    priority_filter = ''
    if form.is_valid():
        search_query = (form.cleaned_data.get('search_query') or '').strip()
        status_filter = (form.cleaned_data.get('status_filter') or '').strip()
        priority_filter = (form.cleaned_data.get('priority_filter') or '').strip()

    if search_query:
        queryset = queryset.filter(
            Q(ticket_id__icontains=search_query)
            | Q(title__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(created_by__username__icontains=search_query)
            | Q(assigned_to__username__icontains=search_query)
        )

    if status_filter:
        queryset = queryset.filter(status=status_filter)

    if priority_filter:
        queryset = queryset.filter(priority=priority_filter)

    queryset = queryset.order_by('-created_at')
    paginator = Paginator(queryset, int(request.GET.get('page_size', 25) or 25))
    page_obj = paginator.get_page(request.GET.get('page', 1))
    context = {
        'form': form,
        'page_obj': page_obj,
        'tickets': page_obj,
    }
    return render(request, 'customer_support/tickets/list.html', context)


@login_required
@require_support_staff_access
def ticket_detail(request, ticket_id):
    ticket = get_object_or_404(_get_ticket_queryset(request.user), ticket_id=ticket_id)
    tier = get_user_support_tier(request.user)
    comments = SupportTicketComment.objects.filter(ticket=ticket).select_related('author').order_by('created_at')
    if tier == 'customer':
        comments = comments.filter(is_internal=False)

    context = {
        'ticket': ticket,
        'comments': comments,
        'comment_form': SupportTicketCommentForm(),
        'update_form': SupportTicketUpdateForm(instance=ticket, organization=ticket.organization),
        'is_staff_tier': tier in {'superuser', 'staff', 'support_agent'},
    }
    return render(request, 'customer_support/tickets/detail.html', context)


@login_required
@require_support_staff_access
def ticket_create(request):
    profile = _get_user_profile(request.user)
    if not profile:
        messages.error(request, 'A profile and organization are required to create tickets.')
        return redirect('customer_support:ticket_list')

    form = SupportTicketForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        ticket = form.save(commit=False)
        ticket.organization = profile.organization
        ticket.created_by = request.user
        ticket.save()
        form.save_m2m()

        _log_support_audit(
            user=request.user,
            action='create',
            content_type='SupportTicket',
            object_id=ticket.id,
            object_repr=ticket.ticket_id,
            changes={'status': {'old': None, 'new': ticket.status}},
            request=request,
        )
        _log_ticket_audit(ticket, 'create', request.user, old_value={}, new_value={'status': ticket.status})
        broadcast_ticket_event(ticket, 'ticket.created')
        messages.success(request, f'Ticket {ticket.ticket_id} created.')
        return redirect('customer_support:ticket_detail', ticket_id=ticket.ticket_id)

    return render(request, 'customer_support/tickets/create.html', {'form': form})


@login_required
@require_support_staff_access
def ticket_update(request, ticket_id):
    ticket = get_object_or_404(_get_ticket_queryset(request.user), ticket_id=ticket_id)
    old_values = {
        'status': ticket.status,
        'priority': ticket.priority,
        'assigned_to': ticket.assigned_to_id,
    }

    form = SupportTicketUpdateForm(
        request.POST or None,
        instance=ticket,
        organization=ticket.organization,
    )
    if request.method == 'POST' and form.is_valid():
        updated_ticket = form.save()
        new_values = {
            'status': updated_ticket.status,
            'priority': updated_ticket.priority,
            'assigned_to': updated_ticket.assigned_to_id,
        }
        _log_support_audit(
            user=request.user,
            action='update',
            content_type='SupportTicket',
            object_id=updated_ticket.id,
            object_repr=updated_ticket.ticket_id,
            changes={k: {'old': old_values.get(k), 'new': new_values.get(k)} for k in old_values if old_values[k] != new_values[k]},
            request=request,
        )
        _log_ticket_audit(updated_ticket, 'update', request.user, old_value=old_values, new_value=new_values)
        broadcast_ticket_event(updated_ticket, 'ticket.updated')
        messages.success(request, f'Ticket {updated_ticket.ticket_id} updated.')
        return redirect('customer_support:ticket_detail', ticket_id=updated_ticket.ticket_id)

    return render(request, 'customer_support/tickets/update_modal.html', {'form': form, 'ticket': ticket})


@login_required
@require_support_staff_access
def ticket_add_comment(request, ticket_id):
    ticket = get_object_or_404(_get_ticket_queryset(request.user), ticket_id=ticket_id)
    tier = get_user_support_tier(request.user)
    form = SupportTicketCommentForm(request.POST or None, request.FILES or None)

    if tier == 'customer':
        form.fields['is_internal'].initial = False
        form.fields['is_internal'].widget = form.fields['is_internal'].hidden_widget()

    if request.method == 'POST' and form.is_valid():
        comment = form.save(commit=False)
        comment.ticket = ticket
        comment.author = request.user
        if tier == 'customer':
            comment.is_internal = False
        comment.save()

        _log_support_audit(
            user=request.user,
            action='update',
            content_type='SupportTicketComment',
            object_id=comment.id,
            object_repr=ticket.ticket_id,
            changes={'comment_added': True},
            request=request,
        )
        _log_ticket_audit(ticket, 'comment_added', request.user, old_value={}, new_value={'comment_id': comment.id})
        broadcast_ticket_event(ticket, 'ticket.comment', extra={
            'comment_author': request.user.username,
            'comment_preview': comment.comment_text[:120],
        })
        messages.success(request, 'Comment added.')
        return redirect('customer_support:ticket_detail', ticket_id=ticket.ticket_id)

    messages.error(request, 'Unable to add comment.')
    return redirect('customer_support:ticket_detail', ticket_id=ticket.ticket_id)


@login_required
@require_support_staff_access
def ticket_close(request, ticket_id):
    ticket = get_object_or_404(_get_ticket_queryset(request.user), ticket_id=ticket_id)

    if request.method == 'POST':
        old_status = ticket.status
        ticket.status = 'closed'
        satisfaction_score = request.POST.get('customer_satisfaction_score')
        if satisfaction_score:
            try:
                ticket.customer_satisfaction_score = int(satisfaction_score)
            except ValueError:
                messages.error(request, 'Invalid satisfaction score.')
                return redirect('customer_support:ticket_detail', ticket_id=ticket.ticket_id)
        ticket.save()
        _log_ticket_audit(ticket, 'close', request.user, old_value={'status': old_status}, new_value={'status': 'closed'})
        _log_support_audit(
            user=request.user,
            action='update',
            content_type='SupportTicket',
            object_id=ticket.id,
            object_repr=ticket.ticket_id,
            changes={'status': {'old': old_status, 'new': 'closed'}},
            request=request,
        )
        broadcast_ticket_event(ticket, 'ticket.closed')
        # Schedule CSAT survey email for 24 hours after close
        from .tasks import send_csat_survey_email
        send_csat_survey_email.apply_async(args=[ticket.pk], countdown=86400)
        messages.success(request, f'Ticket {ticket.ticket_id} closed.')
        return redirect('customer_support:ticket_detail', ticket_id=ticket.ticket_id)

    return render(request, 'customer_support/tickets/close_survey.html', {'ticket': ticket})


@login_required
@require_support_admin_access
def ticket_merge(request, ticket_id):
    source_ticket = get_object_or_404(_get_ticket_queryset(request.user), ticket_id=ticket_id)
    old_status = source_ticket.status
    old_archived = source_ticket.is_archived
    if request.method != 'POST':
        messages.error(request, 'POST required.')
        return redirect('customer_support:ticket_detail', ticket_id=source_ticket.ticket_id)

    target_ticket_id = (request.POST.get('merge_into') or '').strip()
    target_ticket = get_object_or_404(_get_ticket_queryset(request.user), ticket_id=target_ticket_id)
    if target_ticket.id == source_ticket.id:
        messages.error(request, 'A ticket cannot be merged into itself.')
        return redirect('customer_support:ticket_detail', ticket_id=source_ticket.ticket_id)

    TicketRelationship.objects.get_or_create(
        from_ticket=source_ticket,
        to_ticket=target_ticket,
        relationship_type='duplicate',
        defaults={'created_by': request.user},
    )
    source_ticket.is_archived = True
    source_ticket.status = 'closed'
    source_ticket.closed_at = timezone.now()
    source_ticket.save(update_fields=['is_archived', 'status', 'closed_at', 'updated_at'])

    _log_ticket_audit(
        source_ticket,
        'merge',
        request.user,
        old_value={'is_archived': old_archived, 'status': old_status},
        new_value={'is_archived': True, 'status': 'closed', 'merged_into': target_ticket.ticket_id},
    )
    messages.success(request, f'{source_ticket.ticket_id} merged into {target_ticket.ticket_id}.')
    return redirect('customer_support:ticket_detail', ticket_id=target_ticket.ticket_id)


@login_required
@require_support_staff_access
def ticket_export(request, ticket_id):
    ticket = get_object_or_404(_get_ticket_queryset(request.user), ticket_id=ticket_id)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{ticket.ticket_id}.csv"'

    writer = csv.writer(response)
    writer.writerow(['ticket_id', 'title', 'status', 'priority', 'category', 'severity', 'created_at', 'updated_at'])
    writer.writerow(
        [
            ticket.ticket_id,
            ticket.title,
            ticket.status,
            ticket.priority,
            ticket.category,
            ticket.severity,
            ticket.created_at.isoformat(),
            ticket.updated_at.isoformat(),
        ]
    )
    return response


@login_required
@require_support_staff_access
def support_analytics(request):
    tickets = _get_ticket_queryset(request.user)
    context = {
        'avg_csat': tickets.aggregate(avg=Avg('customer_satisfaction_score')).get('avg') or 0,
        'status_breakdown': tickets.values('status').annotate(count=Count('id')).order_by('status'),
        'priority_breakdown': tickets.values('priority').annotate(count=Count('id')).order_by('priority'),
    }
    return render(request, 'customer_support/analytics/dashboard.html', context)


@login_required
@require_support_staff_access
def team_performance(request):
    tickets = _get_ticket_queryset(request.user)
    performance = (
        tickets.exclude(assigned_to__isnull=True)
        .values('assigned_to__username')
        .annotate(total_assigned=Count('id'), resolved=Count('id', filter=Q(status='resolved')))
        .order_by('-total_assigned')
    )
    return render(request, 'customer_support/analytics/team_performance.html', {'performance': performance})


@login_required
@require_support_staff_access
def ticket_trends(request):
    tickets = _get_ticket_queryset(request.user)
    trend_rows = (
        tickets.annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(total=Count('id'))
        .order_by('-day')[:30]
    )
    return render(request, 'customer_support/analytics/trends.html', {'trend_rows': reversed(trend_rows)})


# ---------------------------------------------------------------------------
# Knowledge Base views
# ---------------------------------------------------------------------------

def _get_kb_queryset(user, include_drafts=False):
    """Return org-scoped KB articles. Staff/agent can see drafts."""
    profile = _get_user_profile(user)
    if not profile:
        return KBArticle.objects.none()
    qs = KBArticle.objects.select_related('category', 'authored_by').filter(
        organization=profile.organization
    )
    if include_drafts:
        return qs
    tier = get_user_support_tier(user)
    if tier in {'superuser', 'staff', 'support_agent'}:
        return qs  # staff see all statuses
    return qs.filter(status=KBArticle.STATUS_PUBLISHED, is_public=True)


@login_required
@require_support_staff_access
def kb_list(request):
    profile = _get_user_profile(request.user)
    tier = get_user_support_tier(request.user)
    is_staff = tier in {'superuser', 'staff', 'support_agent'}
    articles = _get_kb_queryset(request.user, include_drafts=is_staff)

    search = (request.GET.get('q') or '').strip()
    category_slug = (request.GET.get('category') or '').strip()
    status_filter = (request.GET.get('status') or '').strip()

    if search:
        articles = articles.filter(Q(title__icontains=search) | Q(content__icontains=search))
    if category_slug:
        articles = articles.filter(category__slug=category_slug)
    if is_staff and status_filter:
        articles = articles.filter(status=status_filter)

    categories = (
        KBCategory.objects.filter(organization=profile.organization) if profile else KBCategory.objects.none()
    )
    paginator = Paginator(articles, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'page_obj': page_obj,
        'categories': categories,
        'search': search,
        'category_slug': category_slug,
        'status_filter': status_filter,
        'is_staff': is_staff,
    }
    return render(request, 'customer_support/kb/list.html', context)


@login_required
@require_support_staff_access
def kb_article_detail(request, slug):
    profile = _get_user_profile(request.user)
    qs = KBArticle.objects.select_related('category', 'authored_by').filter(
        organization=profile.organization if profile else None
    )
    article = get_object_or_404(qs, slug=slug)
    tier = get_user_support_tier(request.user)
    is_staff = tier in {'superuser', 'staff', 'support_agent'}

    # Customers can only see published public articles
    if not is_staff and (article.status != KBArticle.STATUS_PUBLISHED or not article.is_public):
        messages.error(request, 'Article not found.')
        return redirect('customer_support:kb_list')

    # Increment view counter (simple, non-atomic is fine for analytics)
    KBArticle.objects.filter(pk=article.pk).update(view_count=article.view_count + 1)

    context = {
        'article': article,
        'is_staff': is_staff,
        'related_tickets': article.related_tickets.all() if is_staff else None,
    }
    return render(request, 'customer_support/kb/detail.html', context)


@login_required
@require_support_staff_access
def kb_article_create(request):
    profile = _get_user_profile(request.user)
    if not profile:
        messages.error(request, 'A profile and organisation are required.')
        return redirect('customer_support:kb_list')

    form = KBArticleForm(request.POST or None, organization=profile.organization)
    if request.method == 'POST' and form.is_valid():
        article = form.save(commit=False)
        article.organization = profile.organization
        article.authored_by = request.user
        article.save()
        messages.success(request, f'Article "{article.title}" created.')
        return redirect('customer_support:kb_article_detail', slug=article.slug)

    return render(request, 'customer_support/kb/create.html', {'form': form})


@login_required
@require_support_staff_access
def kb_article_edit(request, slug):
    profile = _get_user_profile(request.user)
    article = get_object_or_404(KBArticle, slug=slug, organization=profile.organization if profile else None)

    form = KBArticleForm(request.POST or None, instance=article, organization=profile.organization if profile else None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Article updated.')
        return redirect('customer_support:kb_article_detail', slug=article.slug)

    return render(request, 'customer_support/kb/edit.html', {'form': form, 'article': article})


@login_required
@require_support_staff_access
def kb_article_helpful(request, slug):
    """AJAX endpoint: POST with `{"helpful": true/false}`."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)

    profile = _get_user_profile(request.user)
    article = get_object_or_404(KBArticle, slug=slug, organization=profile.organization if profile else None)
    import json as _json
    try:
        data = _json.loads(request.body)
    except _json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if data.get('helpful'):
        KBArticle.objects.filter(pk=article.pk).update(helpful_count=article.helpful_count + 1)
    else:
        KBArticle.objects.filter(pk=article.pk).update(not_helpful_count=article.not_helpful_count + 1)
    return JsonResponse({'success': True})


# ---------------------------------------------------------------------------
# Customer self-service portal views
# ---------------------------------------------------------------------------

@login_required
@require_customer_access
def customer_portal_home(request):
    profile = _get_user_profile(request.user)
    my_tickets = (
        SupportTicket.objects.filter(created_by=request.user, is_archived=False)
        .order_by('-created_at')[:5]
        if profile else []
    )
    published_kb = (
        KBArticle.objects.filter(
            organization=profile.organization,
            status=KBArticle.STATUS_PUBLISHED,
            is_public=True,
        ).order_by('-view_count')[:6]
        if profile else []
    )
    context = {
        'my_tickets': my_tickets,
        'popular_articles': published_kb,
        'open_count': SupportTicket.objects.filter(
            created_by=request.user, is_archived=False
        ).exclude(status__in=['resolved', 'closed']).count() if profile else 0,
    }
    return render(request, 'customer_support/portal/home.html', context)


@login_required
@require_customer_access
def customer_my_tickets(request):
    profile = _get_user_profile(request.user)
    tickets = SupportTicket.objects.filter(
        created_by=request.user, is_archived=False
    ).order_by('-created_at')

    status_filter = (request.GET.get('status') or '').strip()
    if status_filter:
        tickets = tickets.filter(status=status_filter)

    paginator = Paginator(tickets, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'status_choices': SupportTicket.STATUS_CHOICES,
    }
    return render(request, 'customer_support/portal/my_tickets.html', context)


@login_required
@require_customer_access
def customer_ticket_create(request):
    profile = _get_user_profile(request.user)
    if not profile:
        messages.error(request, 'A profile and organisation are required to submit a ticket.')
        return redirect('customer_support:portal_home')

    from .forms import CustomerTicketCreateForm
    form = CustomerTicketCreateForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        ticket = form.save(commit=False)
        ticket.organization = profile.organization
        ticket.created_by = request.user
        ticket.save()
        form.save_m2m()
        broadcast_ticket_event(ticket, 'ticket.created')
        messages.success(request, f'Your ticket {ticket.ticket_id} has been submitted. We will get back to you soon.')
        return redirect('customer_support:customer_ticket_detail', ticket_id=ticket.ticket_id)

    return render(request, 'customer_support/portal/create.html', {'form': form})


@login_required
@require_customer_access
def customer_ticket_detail(request, ticket_id):
    ticket = get_object_or_404(
        SupportTicket,
        ticket_id=ticket_id,
        created_by=request.user,
        is_archived=False,
    )
    comments = SupportTicketComment.objects.filter(ticket=ticket, is_internal=False).select_related('author').order_by('created_at')
    comment_form = SupportTicketCommentForm()

    if request.method == 'POST':
        comment_form = SupportTicketCommentForm(request.POST, request.FILES)
        if comment_form.is_valid():
            comment = comment_form.save(commit=False)
            comment.ticket = ticket
            comment.author = request.user
            comment.is_internal = False
            comment.save()
            broadcast_ticket_event(ticket, 'ticket.comment', extra={
                'comment_author': request.user.username,
                'comment_preview': comment.comment_text[:120],
            })
            messages.success(request, 'Reply sent.')
            return redirect('customer_support:customer_ticket_detail', ticket_id=ticket.ticket_id)

    context = {
        'ticket': ticket,
        'comments': comments,
        'comment_form': comment_form,
    }
    return render(request, 'customer_support/portal/ticket_detail.html', context)

