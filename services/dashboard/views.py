from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Max
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from core.models import UserProfile
from core.views import require_organization_access

from .models import Conversation, ConversationParticipant, Message


def _get_profile(request):
    try:
        return request.user.mediap_profile
    except (UserProfile.DoesNotExist, AttributeError):
        return None


def _get_participant_or_404(conversation_id, profile):
    return get_object_or_404(
        ConversationParticipant.objects.select_related("conversation"),
        conversation_id=conversation_id,
        user_profile=profile,
        is_active=True,
        conversation__is_active=True,
        conversation__organization=profile.organization,
    )


@login_required
@require_organization_access
def index(request):
    return overview(request)


@login_required
@require_organization_access
def overview(request):
    return render(request, "service_dashboard/overview.html")


@login_required
@require_organization_access
def notifications(request):
    return render(request, "service_dashboard/notifications.html")


@login_required
@require_organization_access
def settings(request):
    return render(request, "service_dashboard/settings.html")


@login_required
@require_organization_access
def calendar(request):
    return render(request, "service_dashboard/calendar.html")


@login_required
@require_organization_access
def messages(request):
    profile = _get_profile(request)
    if not profile:
        raise Http404("Profile not found")

    memberships = (
        ConversationParticipant.objects.filter(
            user_profile=profile,
            is_active=True,
            conversation__is_active=True,
            conversation__organization=profile.organization,
        )
        .select_related("conversation")
        .annotate(last_msg_at=Max("conversation__messages__created_at"))
        .order_by("-conversation__last_message_at", "-conversation__created_at")
    )

    members = UserProfile.objects.filter(
        organization=profile.organization,
        is_active=True,
    ).exclude(pk=profile.pk).select_related("user")

    return render(
        request,
        "service_dashboard/messages.html",
        {
            "memberships": memberships,
            "members": members,
        },
    )


@login_required
@require_organization_access
def thread(request, conversation_id):
    profile = _get_profile(request)
    participant = _get_participant_or_404(conversation_id, profile)

    msgs = (
        Message.objects.filter(conversation=participant.conversation, is_deleted=False)
        .select_related("sender", "sender__user")
        .order_by("created_at")[:200]
    )

    return render(
        request,
        "service_dashboard/thread.html",
        {
            "conversation": participant.conversation,
            "messages": msgs,
        },
    )


@login_required
@require_organization_access
@require_POST
def start_direct(request):
    profile = _get_profile(request)
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
def send_message(request, conversation_id):
    profile = _get_profile(request)
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
    participant = _get_participant_or_404(conversation_id, profile)

    latest = (
        Message.objects.filter(conversation=participant.conversation, is_deleted=False)
        .order_by("-created_at")
        .first()
    )
    participant.last_read_message = latest
    participant.save(update_fields=["last_read_message"])
    return JsonResponse({"ok": True, "last_read_message_id": latest.id if latest else None})