import logging

from celery import shared_task
from django.db.models import Min, Q
from django.utils import timezone

from .models import Conversation, ConversationParticipant, DashboardPreference, Message


logger = logging.getLogger(__name__)


@shared_task
def enforce_message_retention():
    default_retention_days = DashboardPreference._meta.get_field("message_retention_days").default
    now = timezone.now()
    conversations = Conversation.objects.filter(is_active=True).annotate(
        retention_days=Min(
            "participants__user_profile__dashboard_preferences__message_retention_days",
            filter=Q(participants__is_active=True),
        )
    )

    updated_conversations = 0
    deleted_messages = 0

    for conversation in conversations.iterator():
        retention_days = conversation.retention_days or default_retention_days
        cutoff = now - timezone.timedelta(days=retention_days)
        old_message_ids = list(
            Message.objects.filter(
                conversation=conversation,
                is_deleted=False,
                created_at__lt=cutoff,
            ).values_list("id", flat=True)
        )

        if not old_message_ids:
            continue

        deleted_messages += Message.objects.filter(id__in=old_message_ids).update(
            is_deleted=True,
            deleted_at=now,
        )

        latest_remaining = (
            Message.objects.filter(conversation=conversation, is_deleted=False)
            .order_by("-created_at")
            .first()
        )
        ConversationParticipant.objects.filter(
            conversation=conversation,
            last_read_message_id__in=old_message_ids,
        ).update(last_read_message=latest_remaining)
        Conversation.objects.filter(pk=conversation.pk).update(
            last_message_at=latest_remaining.created_at if latest_remaining else conversation.created_at
        )
        updated_conversations += 1

    logger.info(
        "Dashboard retention enforcement completed for %s conversations and %s messages",
        updated_conversations,
        deleted_messages,
    )
    return {
        "updated_conversations": updated_conversations,
        "deleted_messages": deleted_messages,
    }