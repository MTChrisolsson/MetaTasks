from django.urls import path
from . import views

app_name = "service_dashboard"

urlpatterns = [
    path("", views.index, name="index"),
    path("overview/", views.overview, name="overview"),
    path("notifications/", views.notifications, name="notifications"),
    path("settings/", views.settings, name="settings"),
    path("calendar/", views.calendar, name="calendar"),

    path("messages/", views.messages, name="messages"),
    path("messages/start-direct/", views.start_direct, name="start_direct"),
    path("messages/<int:conversation_id>/", views.thread, name="thread"),
    path("messages/<int:conversation_id>/send/", views.send_message, name="send_message"),
    path("messages/<int:conversation_id>/poll/", views.poll_messages, name="poll_messages"),
    path("messages/<int:conversation_id>/mark-read/", views.mark_read, name="mark_read"),
]