from django.contrib import admin
from .models import Conversation, ConversationParticipant, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "organization", "conversation_type", "title", "last_message_at", "is_active")
    list_filter = ("conversation_type", "is_active", "organization")
    search_fields = ("title", "organization__name")
    readonly_fields = ("created_at", "last_message_at")


@admin.register(ConversationParticipant)
class ConversationParticipantAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "user_profile", "is_active", "joined_at")
    list_filter = ("is_active",)
    search_fields = ("user_profile__user__username", "user_profile__user__email")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender", "created_at", "is_edited", "is_deleted")
    list_filter = ("is_edited", "is_deleted", "created_at")
    search_fields = ("body", "sender__user__username", "conversation__title")
    readonly_fields = ("created_at",)