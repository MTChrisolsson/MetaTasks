from collections import defaultdict
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Max, F, Prefetch, Subquery, OuterRef
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.models import CalendarEvent, Notification, Team, UserProfile
from core.services.permission_service import PermissionService
from core.views import require_organization_access
from services.scheduling.models import BookingRequest, SchedulableResource

from .models import Conversation, ConversationParticipant, DashboardPreference, Message


MESSAGES_PERMISSION = "user.view"
CALENDAR_PERMISSIONS = ("scheduling.view", "booking.view")
ACTIVE_BOOKING_STATUSES = ("pending", "confirmed", "in_progress")
DEFAULT_CALENDAR_STATUS = "scheduled"
NOTIFICATIONS_PER_PAGE = 20


def _get_profile(request):
    try:
        return request.user.mediap_profile
    except (UserProfile.DoesNotExist, AttributeError):
        return None


def _get_preferences(profile):
    preferences, _ = DashboardPreference.objects.get_or_create(
        user_profile=profile,
        defaults={
            "email_alerts": profile.email_notifications,
            "desktop_notifications": profile.desktop_notifications,
        },
    )
    return preferences


def _get_participant_or_404(conversation_id, profile):
    return get_object_or_404(
        ConversationParticipant.objects.select_related("conversation").prefetch_related(
            Prefetch(
                "conversation__participants",
                queryset=ConversationParticipant.objects.select_related("user_profile__user"),
            )
        ),
        conversation_id=conversation_id,
        user_profile=profile,
        is_active=True,
        conversation__is_active=True,
        conversation__organization=profile.organization,
    )


def _get_memberships(profile):
    return ConversationParticipant.objects.filter(
        user_profile=profile,
        is_active=True,
        conversation__is_active=True,
        conversation__organization=profile.organization,
    ).select_related("conversation").prefetch_related(
        Prefetch(
            "conversation__participants",
            queryset=ConversationParticipant.objects.select_related("user_profile__user"),
        )
    )



def _get_memberships_with_preview(profile):
    """Like _get_memberships but annotates preview_body (last non-deleted message body)."""
    last_msg_body = Subquery(
        Message.objects.filter(
            conversation=OuterRef("conversation_id"),
            is_deleted=False,
        ).order_by("-created_at").values("body")[:1]
    )
    return (
        ConversationParticipant.objects.filter(
            user_profile=profile,
            is_active=True,
            conversation__is_active=True,
            conversation__organization=profile.organization,
        )
        .select_related("conversation", "last_read_message")
        .prefetch_related(
            Prefetch(
                "conversation__participants",
                queryset=ConversationParticipant.objects.select_related("user_profile__user"),
            )
        )
        .annotate(preview_body=last_msg_body)
        .order_by("-conversation__last_message_at", "-conversation__created_at")
    )


def _apply_unread_flags(memberships, current_conversation_id=None):
    """Stamps .is_unread on each membership in-place (list expected)."""
    for m in memberships:
        if m.conversation.id == current_conversation_id:
            m.is_unread = False
        elif m.preview_body is None:
            m.is_unread = False
        elif m.last_read_message_id is None:
            m.is_unread = True
        else:
            m.is_unread = m.last_read_message.created_at < m.conversation.last_message_at



def _has_any_permission(profile, permission_codenames):
    permission_service = PermissionService(profile.organization)
    return any(
        permission_service.has_permission(profile, permission_codename)
        for permission_codename in permission_codenames
    )


def _deny_dashboard_access(request, message):
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": False, "error": message}, status=403)
    raise PermissionDenied(message)


def _require_dashboard_access(request, profile, permission_codenames, message):
    if _has_any_permission(profile, permission_codenames):
        return None
    return _deny_dashboard_access(request, message)


def _safe_next_url(request, default_url):
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return default_url


def _parse_int_filter(raw_value):
    if raw_value and raw_value.isdigit():
        return int(raw_value)
    return None


def _build_dashboard_shell_context(profile, preferences=None):
    can_access_messages = _has_any_permission(profile, (MESSAGES_PERMISSION,))
    can_access_calendar = _has_any_permission(profile, CALENDAR_PERMISSIONS)
    memberships = _get_memberships(profile) if can_access_messages else ConversationParticipant.objects.none()

    unread_thread_count = 0
    if can_access_messages:
        unread_thread_count = (
            memberships.filter(
                Q(last_read_message__isnull=True, conversation__messages__is_deleted=False)
                | Q(last_read_message__created_at__lt=F("conversation__last_message_at"))
            )
            .values("conversation_id")
            .distinct()
            .count()
        )

    return {
        "preferences": preferences or _get_preferences(profile),
        "unread_thread_count": unread_thread_count,
        "unread_notifications_count": Notification.objects.filter(
            recipient=profile.user,
            is_read=False,
        ).count(),
        "can_access_messages": can_access_messages,
        "can_access_calendar": can_access_calendar,
    }


def _set_conversation_display_titles(conversations, viewer_profile):
    for conversation in conversations:
        conversation.display_title = conversation.get_display_title(viewer_profile)


@login_required
@require_organization_access
def index(request):
    return overview(request)


@login_required
@require_organization_access
def overview(request):
    profile = _get_profile(request)
    if not profile:
        raise Http404("Profile not found")

    preferences = _get_preferences(profile)
    shell_context = _build_dashboard_shell_context(profile, preferences=preferences)
    memberships = _get_memberships(profile) if shell_context["can_access_messages"] else ConversationParticipant.objects.none()

    recent_threads = memberships.order_by("-conversation__last_message_at", "-conversation__created_at")[:5]
    _set_conversation_display_titles(
        [membership.conversation for membership in recent_threads],
        profile,
    )
    recent_notifications = Notification.objects.filter(recipient=request.user).order_by("-created_at")[:5]

    now = timezone.now()
    seven_days = now + timezone.timedelta(days=7)
    upcoming_events = CalendarEvent.objects.none()
    upcoming_bookings = BookingRequest.objects.none()
    if shell_context["can_access_calendar"]:
        upcoming_events = CalendarEvent.objects.filter(
            organization=profile.organization,
            is_cancelled=False,
            start_time__gte=now,
            start_time__lte=seven_days,
        ).select_related("created_by__user", "related_team").order_by("start_time")[:5]
        upcoming_bookings = BookingRequest.objects.filter(
            organization=profile.organization,
            requested_start__gte=now,
            requested_start__lte=seven_days,
            status__in=ACTIVE_BOOKING_STATUSES,
        ).select_related("resource", "requested_by__user").order_by("requested_start")[:5]

    context = {
        **shell_context,
        "preferences": preferences,
        "active_threads_count": memberships.count(),
        "upcoming_total_count": len(upcoming_events) + len(upcoming_bookings),
        "organization_member_count": UserProfile.objects.filter(
            organization=profile.organization,
            is_active=True,
        ).count(),
        "recent_threads": recent_threads,
        "recent_notifications": recent_notifications,
        "upcoming_events": upcoming_events,
        "upcoming_bookings": upcoming_bookings,
    }
    return render(request, "service_dashboard/overview.html", context)


@login_required
@require_organization_access
def notifications(request):
    profile = _get_profile(request)
    if not profile:
        raise Http404("Profile not found")

    preferences = _get_preferences(profile)
    shell_context = _build_dashboard_shell_context(profile, preferences=preferences)
    filter_value = request.GET.get("filter", "all")
    if filter_value not in {"all", "unread"}:
        filter_value = "all"

    notifications_qs = Notification.objects.filter(recipient=request.user)
    if filter_value == "unread":
        notifications_qs = notifications_qs.filter(is_read=False)

    notifications_qs = notifications_qs.order_by("-created_at")
    page_obj = Paginator(notifications_qs, NOTIFICATIONS_PER_PAGE).get_page(request.GET.get("page") or 1)
    pagination_query = urlencode({"filter": filter_value}) if filter_value != "all" else ""

    return render(
        request,
        "service_dashboard/notifications.html",
        {
            **shell_context,
            "preferences": preferences,
            "notifications": page_obj.object_list,
            "page_obj": page_obj,
            "filter": filter_value,
            "pagination_query": pagination_query,
            "unread_count": shell_context["unread_notifications_count"],
            "total_count": Notification.objects.filter(recipient=request.user).count(),
        },
    )


@login_required
@require_organization_access
@require_POST
def mark_notification_read(request, notification_id):
    notification = get_object_or_404(Notification, pk=notification_id, recipient=request.user)
    notification.mark_as_read()
    next_url = _safe_next_url(request, reverse("service_dashboard:notifications"))

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "notification_id": notification.id})

    return redirect(next_url)


@login_required
@require_organization_access
@require_POST
def mark_all_notifications_read(request):
    unread = Notification.objects.filter(recipient=request.user, is_read=False)
    now = timezone.now()
    updated_count = unread.update(is_read=True, read_at=now)
    next_url = _safe_next_url(request, reverse("service_dashboard:notifications"))

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "updated_count": updated_count})

    return redirect(next_url)


@login_required
@require_organization_access
@require_POST
def bulk_notification_action(request):
    action = request.POST.get("bulk_action")
    next_url = _safe_next_url(request, reverse("service_dashboard:notifications"))
    notification_ids = [int(value) for value in request.POST.getlist("notification_ids") if value.isdigit()]

    if not notification_ids:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "error": "Select at least one notification."}, status=400)
        return redirect(next_url)

    notifications_qs = Notification.objects.filter(recipient=request.user, id__in=notification_ids)
    now = timezone.now()

    if action == "mark_read":
        affected_count = notifications_qs.update(is_read=True, read_at=now)
    elif action == "mark_unread":
        affected_count = notifications_qs.update(is_read=False, read_at=None)
    elif action == "delete":
        affected_count = notifications_qs.delete()[0]
    else:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "error": "Unsupported bulk action."}, status=400)
        return redirect(next_url)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "affected_count": affected_count})

    return redirect(next_url)


@login_required
@require_organization_access
def settings(request):
    profile = _get_profile(request)
    if not profile:
        raise Http404("Profile not found")

    preferences = _get_preferences(profile)
    shell_context = _build_dashboard_shell_context(profile, preferences=preferences)
    saved = False

    if request.method == "POST":
        preferences.show_read_receipts = bool(request.POST.get("show_read_receipts"))
        preferences.desktop_notifications = bool(request.POST.get("desktop_notifications"))
        preferences.auto_mark_threads_read = bool(request.POST.get("auto_mark_threads_read"))
        preferences.email_alerts = bool(request.POST.get("email_alerts"))

        digest_frequency = request.POST.get("digest_frequency", preferences.digest_frequency)
        if digest_frequency in dict(DashboardPreference.DIGEST_CHOICES):
            preferences.digest_frequency = digest_frequency

        retention_days = request.POST.get("message_retention_days", preferences.message_retention_days)
        try:
            retention_days = int(retention_days)
        except (TypeError, ValueError):
            retention_days = preferences.message_retention_days
        if retention_days in {30, 90, 180, 365}:
            preferences.message_retention_days = retention_days

        default_visibility = request.POST.get("default_visibility", preferences.default_visibility)
        if default_visibility in dict(DashboardPreference.VISIBILITY_CHOICES):
            preferences.default_visibility = default_visibility

        preferences.save()
        profile.email_notifications = preferences.email_alerts
        profile.desktop_notifications = preferences.desktop_notifications
        profile.save(update_fields=["email_notifications", "desktop_notifications"])
        saved = True

    return render(
        request,
        "service_dashboard/settings.html",
        {
            **shell_context,
            "preferences": preferences,
            "saved": saved,
            "retention_choices": [30, 90, 180, 365],
            "visibility_choices": DashboardPreference.VISIBILITY_CHOICES,
            "digest_choices": DashboardPreference.DIGEST_CHOICES,
        },
    )


@login_required
@require_organization_access
def calendar(request):
    profile = _get_profile(request)
    if not profile:
        raise Http404("Profile not found")

    permission_response = _require_dashboard_access(
        request,
        profile,
        CALENDAR_PERMISSIONS,
        "You do not have permission to access the scheduling calendar from the dashboard.",
    )
    if permission_response:
        return permission_response

    shell_context = _build_dashboard_shell_context(profile)

    now = timezone.now()
    start = now.date()
    end = start + timezone.timedelta(days=30)

    event_type_filter = request.GET.get("event_type", "all")
    if event_type_filter not in {choice[0] for choice in CalendarEvent.EVENT_TYPES} | {"all"}:
        event_type_filter = "all"

    valid_statuses = {choice[0] for choice in BookingRequest.STATUS_CHOICES} | {"all", "scheduled", "cancelled"}
    status_filter = request.GET.get("status", DEFAULT_CALENDAR_STATUS)
    if status_filter not in valid_statuses:
        status_filter = DEFAULT_CALENDAR_STATUS

    team_filter = _parse_int_filter(request.GET.get("team"))
    resource_filter = _parse_int_filter(request.GET.get("resource"))

    events = CalendarEvent.objects.filter(
        organization=profile.organization,
        start_time__date__gte=start,
        start_time__date__lte=end,
    )
    if event_type_filter != "all":
        events = events.filter(event_type=event_type_filter)
    if team_filter:
        events = events.filter(related_team_id=team_filter)
    if status_filter == "scheduled":
        events = events.filter(is_cancelled=False)
    elif status_filter == "cancelled":
        events = events.filter(is_cancelled=True)
    elif status_filter != "all":
        events = events.none()

    events = events.select_related("created_by__user", "related_team").order_by("start_time")[:100]

    bookings = BookingRequest.objects.filter(
        organization=profile.organization,
        requested_start__date__gte=start,
        requested_start__date__lte=end,
    )
    if team_filter:
        bookings = bookings.filter(resource__linked_team_id=team_filter)
    if resource_filter:
        bookings = bookings.filter(resource_id=resource_filter)
    if status_filter == "scheduled":
        bookings = bookings.filter(status__in=ACTIVE_BOOKING_STATUSES)
    elif status_filter == "cancelled":
        bookings = bookings.filter(status="cancelled")
    elif status_filter != "all":
        bookings = bookings.filter(status=status_filter)

    bookings = bookings.select_related("resource", "resource__linked_team", "requested_by__user").order_by("requested_start")[:100]

    timeline_items = []
    for event in events:
        timeline_items.append(
            {
                "kind": "event",
                "kind_label": "Event",
                "title": event.title,
                "start": event.start_time,
                "end": event.end_time,
                "meta": event.related_team.name if event.related_team else (event.created_by.user.get_full_name() or event.created_by.user.username),
                "type_label": event.get_event_type_display(),
                "status_label": "Cancelled" if event.is_cancelled else "Scheduled",
                "link": None,
            }
        )
    for booking in bookings:
        timeline_items.append(
            {
                "kind": "booking",
                "kind_label": "Booking",
                "title": booking.title,
                "start": booking.requested_start,
                "end": booking.requested_end,
                "meta": booking.resource.name,
                "type_label": booking.resource.get_resource_type_display(),
                "status_label": booking.get_status_display(),
                "link": "/services/scheduling/",
            }
        )

    timeline_items.sort(key=lambda item: item["start"])
    grouped_items = defaultdict(list)
    for item in timeline_items:
        grouped_items[item["start"].date()].append(item)

    return render(
        request,
        "service_dashboard/calendar.html",
        {
            **shell_context,
            "date_groups": list(grouped_items.items()),
            "event_count": len(events),
            "booking_count": len(bookings),
            "range_end": end,
            "event_type_choices": CalendarEvent.EVENT_TYPES,
            "status_choices": [
                ("all", "All statuses"),
                ("scheduled", "Scheduled"),
                ("cancelled", "Cancelled"),
                *BookingRequest.STATUS_CHOICES,
            ],
            "teams": Team.objects.filter(
                organization=profile.organization,
                is_active=True,
            ).order_by("name"),
            "resources": SchedulableResource.objects.filter(
                organization=profile.organization,
                is_active=True,
            ).select_related("linked_team").order_by("name"),
            "selected_filters": {
                "event_type": event_type_filter,
                "status": status_filter,
                "team": team_filter,
                "resource": resource_filter,
            },
        },
    )


@login_required
@require_organization_access
def messages(request):
    profile = _get_profile(request)
    if not profile:
        raise Http404("Profile not found")

    permission_response = _require_dashboard_access(
        request,
        profile,
        (MESSAGES_PERMISSION,),
        "You do not have permission to access dashboard messaging.",
    )
    if permission_response:
        return permission_response

    shell_context = _build_dashboard_shell_context(profile)

    memberships = list(_get_memberships_with_preview(profile))
    _set_conversation_display_titles([m.conversation for m in memberships], profile)
    _apply_unread_flags(memberships)

    members = UserProfile.objects.filter(
        organization=profile.organization,
        is_active=True,
    ).exclude(pk=profile.pk).select_related("user")

    return render(
        request,
        "service_dashboard/messages.html",
        {
            **shell_context,
            "memberships": memberships,
            "members": members,
        },
    )


@login_required
@require_organization_access
def thread(request, conversation_id):
    profile = _get_profile(request)
    permission_response = _require_dashboard_access(
        request,
        profile,
        (MESSAGES_PERMISSION,),
        "You do not have permission to access dashboard messaging.",
    )
    if permission_response:
        return permission_response

    participant = _get_participant_or_404(conversation_id, profile)
    preferences = _get_preferences(profile)
    shell_context = _build_dashboard_shell_context(profile, preferences=preferences)
    participant.conversation.display_title = participant.conversation.get_display_title(profile)

    msgs = (
        Message.objects.filter(conversation=participant.conversation, is_deleted=False)
        .select_related("sender", "sender__user")
        .order_by("created_at")[:200]
    )

    if preferences.auto_mark_threads_read and msgs:
        latest = msgs[len(msgs) - 1]
        if participant.last_read_message_id != latest.id:
            participant.last_read_message = latest
            participant.save(update_fields=["last_read_message"])

    # Sidebar data: all conversations with preview + unread flags
    side_memberships = list(_get_memberships_with_preview(profile))
    _set_conversation_display_titles([m.conversation for m in side_memberships], profile)
    _apply_unread_flags(side_memberships, current_conversation_id=participant.conversation.id)

    members = UserProfile.objects.filter(
        organization=profile.organization,
        is_active=True,
    ).exclude(pk=profile.pk).select_related("user")

    active_participants = participant.conversation._get_active_participants()

    return render(
        request,
        "service_dashboard/thread.html",
        {
            **shell_context,
            "conversation": participant.conversation,
            "conversation_display_title": participant.conversation.display_title,
            "messages": msgs,
            "preferences": preferences,
            "memberships": side_memberships,
            "members": members,
            "participants_count": len(active_participants),
        },
    )


@login_required
@require_organization_access
@require_POST
def start_direct(request):
    profile = _get_profile(request)
    permission_response = _require_dashboard_access(
        request,
        profile,
        (MESSAGES_PERMISSION,),
        "You do not have permission to start dashboard conversations.",
    )
    if permission_response:
        return permission_response

    target_id = request.POST.get("target_profile_id")

    if not target_id:
        return JsonResponse({"ok": False, "error": "target_profile_id is required"}, status=400)

    target = get_object_or_404(
        UserProfile,
        pk=target_id,
        organization=profile.organization,
        is_active=True,
    )

    if target.pk == profile.pk:
        return JsonResponse({"ok": False, "error": "Cannot chat with yourself"}, status=400)

    existing = (
        Conversation.objects.filter(
            organization=profile.organization,
            conversation_type=Conversation.TYPE_DIRECT,
            is_active=True,
            participants__user_profile=profile,
            participants__is_active=True,
        )
        .filter(participants__user_profile=target, participants__is_active=True)
        .distinct()
        .first()
    )
    if existing:
        return JsonResponse({"ok": True, "conversation_id": existing.id})

    with transaction.atomic():
        conv = Conversation.objects.create(
            organization=profile.organization,
            conversation_type=Conversation.TYPE_DIRECT,
            created_by=profile,
        )
        ConversationParticipant.objects.create(conversation=conv, user_profile=profile)
        ConversationParticipant.objects.create(conversation=conv, user_profile=target)

    return JsonResponse({"ok": True, "conversation_id": conv.id})


@login_required
@require_organization_access
@require_POST
def rename_conversation(request, conversation_id):
    profile = _get_profile(request)
    permission_response = _require_dashboard_access(
        request,
        profile,
        (MESSAGES_PERMISSION,),
        "You do not have permission to rename dashboard conversations.",
    )
    if permission_response:
        return permission_response

    participant = _get_participant_or_404(conversation_id, profile)
    conversation = participant.conversation
    title = (request.POST.get("title") or "").strip()
    if len(title) > 255:
        return JsonResponse({"ok": False, "error": "Conversation name is too long."}, status=400)

    conversation.title = title
    conversation.save(update_fields=["title"])
    display_title = conversation.get_display_title(profile)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "ok": True,
                "title": conversation.title,
                "display_title": display_title,
                "uses_custom_title": bool(conversation.title),
            }
        )

    return redirect(reverse("service_dashboard:thread", args=[conversation.id]))


@login_required
@require_organization_access
@require_POST
def send_message(request, conversation_id):
    profile = _get_profile(request)
    permission_response = _require_dashboard_access(
        request,
        profile,
        (MESSAGES_PERMISSION,),
        "You do not have permission to send dashboard messages.",
    )
    if permission_response:
        return permission_response

    participant = _get_participant_or_404(conversation_id, profile)

    body = (request.POST.get("body") or "").strip()
    if not body:
        return JsonResponse({"ok": False, "error": "Message body is required"}, status=400)

    msg = Message.objects.create(
        conversation=participant.conversation,
        sender=profile,
        body=body,
    )

    return JsonResponse(
        {
            "ok": True,
            "message": {
                "id": msg.id,
                "body": msg.body,
                "sender_id": msg.sender_id,
                "sender_name": msg.sender.user.get_full_name() or msg.sender.user.username,
                "created_at": msg.created_at.isoformat(),
            },
        }
    )


@login_required
@require_organization_access
@require_GET
def poll_messages(request, conversation_id):
    profile = _get_profile(request)
    permission_response = _require_dashboard_access(
        request,
        profile,
        (MESSAGES_PERMISSION,),
        "You do not have permission to access dashboard messaging.",
    )
    if permission_response:
        return permission_response

    participant = _get_participant_or_404(conversation_id, profile)

    after_id = request.GET.get("after_id")
    qs = Message.objects.filter(
        conversation=participant.conversation,
        is_deleted=False,
    ).select_related("sender", "sender__user").order_by("created_at")

    if after_id and after_id.isdigit():
        qs = qs.filter(id__gt=int(after_id))

    data = [
        {
            "id": m.id,
            "body": m.body,
            "sender_id": m.sender_id,
            "sender_name": m.sender.user.get_full_name() or m.sender.user.username,
            "created_at": m.created_at.isoformat(),
        }
        for m in qs[:100]
    ]
    return JsonResponse({"ok": True, "messages": data})


@login_required
@require_organization_access
@require_POST
def mark_read(request, conversation_id):
    profile = _get_profile(request)
    permission_response = _require_dashboard_access(
        request,
        profile,
        (MESSAGES_PERMISSION,),
        "You do not have permission to access dashboard messaging.",
    )
    if permission_response:
        return permission_response

    participant = _get_participant_or_404(conversation_id, profile)

    latest = (
        Message.objects.filter(conversation=participant.conversation, is_deleted=False)
        .order_by("-created_at")
        .first()
    )
    participant.last_read_message = latest
    participant.save(update_fields=["last_read_message"])
    return JsonResponse({"ok": True, "last_read_message_id": latest.id if latest else None})