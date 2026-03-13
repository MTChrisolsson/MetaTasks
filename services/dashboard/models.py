from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import Organization, UserProfile


class Conversation(models.Model):
    TYPE_DIRECT = "direct"
    TYPE_GROUP = "group"
    TYPE_CHOICES = [
        (TYPE_DIRECT, "Direct"),
        (TYPE_GROUP, "Group"),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="dashboard_conversations",
    )
    conversation_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_DIRECT,
    )
    title = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        UserProfile,
        on_delete=models.SET_NULL,
        null=True,
        related_name="dashboard_conversations_created",
    )
    last_message_at = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        indexes = [
            models.Index(fields=["organization", "last_message_at"]),
            models.Index(fields=["organization", "conversation_type"]),
        ]

    def __str__(self):
        base = self.title or f"{self.get_conversation_type_display()} conversation"
        return f"{base} ({self.organization.name})"

    def clean(self):
        if self.created_by and self.created_by.organization_id != self.organization_id:
            raise ValidationError("Creator must belong to the same organization.")

    def touch(self):
        self.last_message_at = timezone.now()
        self.save(update_fields=["last_message_at"])

class ConversationParticipant(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    user_profile = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name="dashboard_conversation_memberships",
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_message = models.ForeignKey(
        "Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    muted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("conversation", "user_profile")]
        indexes = [
            models.Index(fields=["user_profile", "is_active"]),
            models.Index(fields=["conversation", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user_profile} in {self.conversation_id}"

    def clean(self):
        if self.user_profile.organization_id != self.conversation.organization_id:
            raise ValidationError("Participant must belong to the same organization.")


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name="dashboard_messages_sent",
    )
    body = models.TextField(max_length=4000)
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["sender", "created_at"]),
        ]

    def __str__(self):
        preview = (self.body or "")[:40]
        return f"{self.sender} -> {self.conversation_id}: {preview}"

    def clean(self):
        if self.sender.organization_id != self.conversation.organization_id:
            raise ValidationError("Sender must belong to the same organization.")

    def save(self, *args, **kwargs):
        self.full_clean()
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            Conversation.objects.filter(pk=self.conversation_id).update(
                last_message_at=self.created_at
            )