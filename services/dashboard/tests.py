from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import CalendarEvent, Notification, Organization, Team, UserProfile
from core.services.permission_service import PermissionService
from services.scheduling.models import BookingRequest, SchedulableResource

from .models import Conversation, ConversationParticipant, DashboardPreference, Message
from .tasks import enforce_message_retention


class ServiceDashboardViewsTests(TestCase):
	def setUp(self):
		User = get_user_model()
		self.user = User.objects.create_user(
			username="dashuser",
			email="dash@example.com",
			password="ComplexPass123!",
			first_name="Dash",
			last_name="User",
		)
		self.organization = Organization.objects.create(
			name="Dashboard Org",
			organization_type="business",
			is_active=True,
		)
		self.profile = UserProfile.objects.create(
			user=self.user,
			organization=self.organization,
			is_organization_admin=True,
			has_staff_panel_access=True,
			can_create_organizations=True,
		)
		self.client.login(username="dashuser", password="ComplexPass123!")

	def test_overview_renders_with_live_counts(self):
		conversation = Conversation.objects.create(
			organization=self.organization,
			conversation_type=Conversation.TYPE_DIRECT,
			created_by=self.profile,
			title="Ops thread",
		)
		ConversationParticipant.objects.create(conversation=conversation, user_profile=self.profile)
		Message.objects.create(conversation=conversation, sender=self.profile, body="Hello")

		Notification.objects.create(
			recipient=self.user,
			title="Unread notice",
			message="Needs attention",
			notification_type="info",
		)

		event_start = timezone.now() + timedelta(days=2)
		CalendarEvent.objects.create(
			organization=self.organization,
			title="Standup",
			start_time=event_start,
			end_time=event_start + timedelta(hours=1),
			created_by=self.profile,
		)

		resource = SchedulableResource.objects.create(
			organization=self.organization,
			name="Ops Team",
			resource_type="team",
			is_active=True,
		)
		BookingRequest.objects.create(
			organization=self.organization,
			title="Capacity booking",
			requested_start=event_start,
			requested_end=event_start + timedelta(hours=2),
			resource=resource,
			required_capacity=1,
			source_service="dashboard",
			source_object_type="overview",
			source_object_id="1",
			requested_by=self.profile,
			status="confirmed",
		)

		response = self.client.get(reverse("service_dashboard:overview"))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["active_threads_count"], 1)
		self.assertEqual(response.context["unread_notifications_count"], 1)
		self.assertEqual(response.context["upcoming_total_count"], 2)

	def test_settings_post_persists_preferences(self):
		response = self.client.post(
			reverse("service_dashboard:settings"),
			{
				"show_read_receipts": "on",
				"desktop_notifications": "on",
				"auto_mark_threads_read": "on",
				"email_alerts": "on",
				"digest_frequency": DashboardPreference.DIGEST_DAILY,
				"message_retention_days": "180",
				"default_visibility": DashboardPreference.VISIBILITY_ORGANIZATION,
			},
		)

		self.assertEqual(response.status_code, 200)
		prefs = DashboardPreference.objects.get(user_profile=self.profile)
		self.assertEqual(prefs.digest_frequency, DashboardPreference.DIGEST_DAILY)
		self.assertEqual(prefs.message_retention_days, 180)
		self.assertEqual(
			prefs.default_visibility,
			DashboardPreference.VISIBILITY_ORGANIZATION,
		)

	def test_mark_notification_read_endpoint(self):
		notification = Notification.objects.create(
			recipient=self.user,
			title="Alert",
			message="Investigate",
			notification_type="warning",
			is_read=False,
		)

		response = self.client.post(
			reverse("service_dashboard:mark_notification_read", args=[notification.id]),
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)
		self.assertEqual(response.status_code, 200)

		notification.refresh_from_db()
		self.assertTrue(notification.is_read)

	def test_calendar_groups_items(self):
		start = timezone.now() + timedelta(days=1)
		CalendarEvent.objects.create(
			organization=self.organization,
			title="Planning",
			start_time=start,
			end_time=start + timedelta(hours=1),
			created_by=self.profile,
		)

		response = self.client.get(reverse("service_dashboard:calendar"))
		self.assertEqual(response.status_code, 200)
		self.assertGreaterEqual(len(response.context["date_groups"]), 1)

	def test_notifications_paginates_and_supports_bulk_actions(self):
		notification_ids = []
		for index in range(25):
			notification = Notification.objects.create(
				recipient=self.user,
				title=f"Notice {index}",
				message="Queued",
				notification_type="info",
				is_read=False,
			)
			notification_ids.append(notification.id)

		response = self.client.get(reverse("service_dashboard:notifications"), {"page": 2})
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["page_obj"].number, 2)
		self.assertEqual(len(response.context["notifications"]), 5)

		selected_ids = notification_ids[:2]
		response = self.client.post(
			reverse("service_dashboard:bulk_notification_action"),
			{
				"bulk_action": "mark_read",
				"notification_ids": [str(notification_id) for notification_id in selected_ids],
			},
		)
		self.assertEqual(response.status_code, 302)
		self.assertEqual(
			Notification.objects.filter(id__in=selected_ids, is_read=True).count(),
			2,
		)

	def test_calendar_filters_by_event_type_team_and_resource(self):
		start = timezone.now() + timedelta(days=1)
		primary_team = Team.objects.create(
			organization=self.organization,
			name="Dispatch",
		)
		secondary_team = Team.objects.create(
			organization=self.organization,
			name="Field",
		)
		primary_resource = SchedulableResource.objects.create(
			organization=self.organization,
			name="Dispatch Board",
			resource_type="team",
			linked_team=primary_team,
			is_active=True,
		)
		secondary_resource = SchedulableResource.objects.create(
			organization=self.organization,
			name="Field Van",
			resource_type="equipment",
			linked_team=secondary_team,
			is_active=True,
		)

		CalendarEvent.objects.create(
			organization=self.organization,
			title="Dispatch Review",
			start_time=start,
			end_time=start + timedelta(hours=1),
			created_by=self.profile,
			event_type="team",
			related_team=primary_team,
		)
		CalendarEvent.objects.create(
			organization=self.organization,
			title="Cancelled Field Visit",
			start_time=start,
			end_time=start + timedelta(hours=1),
			created_by=self.profile,
			event_type="team",
			related_team=secondary_team,
			is_cancelled=True,
		)
		BookingRequest.objects.create(
			organization=self.organization,
			title="Dispatch Capacity",
			requested_start=start,
			requested_end=start + timedelta(hours=2),
			resource=primary_resource,
			required_capacity=1,
			source_service="dashboard",
			source_object_type="calendar",
			source_object_id="1",
			requested_by=self.profile,
			status="confirmed",
		)
		BookingRequest.objects.create(
			organization=self.organization,
			title="Field Repair",
			requested_start=start,
			requested_end=start + timedelta(hours=2),
			resource=secondary_resource,
			required_capacity=1,
			source_service="dashboard",
			source_object_type="calendar",
			source_object_id="2",
			requested_by=self.profile,
			status="cancelled",
		)

		response = self.client.get(
			reverse("service_dashboard:calendar"),
			{
				"event_type": "team",
				"status": "scheduled",
				"team": primary_team.id,
				"resource": primary_resource.id,
			},
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["event_count"], 1)
		self.assertEqual(response.context["booking_count"], 1)

	def test_enforce_message_retention_soft_deletes_expired_messages(self):
		conversation = Conversation.objects.create(
			organization=self.organization,
			conversation_type=Conversation.TYPE_DIRECT,
			created_by=self.profile,
		)
		participant = ConversationParticipant.objects.create(
			conversation=conversation,
			user_profile=self.profile,
		)
		DashboardPreference.objects.create(
			user_profile=self.profile,
			message_retention_days=30,
		)

		old_message = Message.objects.create(conversation=conversation, sender=self.profile, body="Old")
		new_message = Message.objects.create(conversation=conversation, sender=self.profile, body="Recent")
		old_timestamp = timezone.now() - timedelta(days=45)
		new_timestamp = timezone.now() - timedelta(days=5)
		Message.objects.filter(pk=old_message.pk).update(created_at=old_timestamp)
		Message.objects.filter(pk=new_message.pk).update(created_at=new_timestamp)
		participant.last_read_message = old_message
		participant.save(update_fields=["last_read_message"])

		result = enforce_message_retention()

		old_message.refresh_from_db()
		new_message.refresh_from_db()
		participant.refresh_from_db()
		self.assertTrue(old_message.is_deleted)
		self.assertFalse(new_message.is_deleted)
		self.assertEqual(participant.last_read_message_id, new_message.id)
		self.assertEqual(result["deleted_messages"], 1)

	def test_conversation_names_use_other_participants_for_direct_and_group_chats(self):
		User = get_user_model()
		other_user = User.objects.create_user(
			username="otherdash",
			email="other@example.com",
			password="ComplexPass123!",
			first_name="Other",
			last_name="Person",
		)
		third_user = User.objects.create_user(
			username="thirddash",
			email="third@example.com",
			password="ComplexPass123!",
			first_name="Third",
			last_name="Person",
		)
		other_profile = UserProfile.objects.create(
			user=other_user,
			organization=self.organization,
		)
		third_profile = UserProfile.objects.create(
			user=third_user,
			organization=self.organization,
		)

		direct_conversation = Conversation.objects.create(
			organization=self.organization,
			conversation_type=Conversation.TYPE_DIRECT,
			created_by=self.profile,
		)
		ConversationParticipant.objects.create(conversation=direct_conversation, user_profile=self.profile)
		ConversationParticipant.objects.create(conversation=direct_conversation, user_profile=other_profile)
		Message.objects.create(conversation=direct_conversation, sender=other_profile, body="Hi")

		group_conversation = Conversation.objects.create(
			organization=self.organization,
			conversation_type=Conversation.TYPE_GROUP,
			created_by=self.profile,
		)
		ConversationParticipant.objects.create(conversation=group_conversation, user_profile=self.profile)
		ConversationParticipant.objects.create(conversation=group_conversation, user_profile=other_profile)
		ConversationParticipant.objects.create(conversation=group_conversation, user_profile=third_profile)
		Message.objects.create(conversation=group_conversation, sender=third_profile, body="Hello team")

		response = self.client.get(reverse("service_dashboard:messages"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Other Person")
		self.assertContains(response, "Other Person, Third Person")
		self.assertNotContains(response, f"Conversation #{direct_conversation.id}")
		self.assertNotContains(response, f"Conversation #{group_conversation.id}")

	def test_rename_conversation_updates_and_can_reset_to_participant_names(self):
		User = get_user_model()
		other_user = User.objects.create_user(
			username="renamepeer",
			email="rename@example.com",
			password="ComplexPass123!",
			first_name="Rename",
			last_name="Peer",
		)
		other_profile = UserProfile.objects.create(
			user=other_user,
			organization=self.organization,
		)
		conversation = Conversation.objects.create(
			organization=self.organization,
			conversation_type=Conversation.TYPE_DIRECT,
			created_by=self.profile,
		)
		ConversationParticipant.objects.create(conversation=conversation, user_profile=self.profile)
		ConversationParticipant.objects.create(conversation=conversation, user_profile=other_profile)

		response = self.client.post(
			reverse("service_dashboard:rename_conversation", args=[conversation.id]),
			{"title": "Priority Support"},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)
		self.assertEqual(response.status_code, 200)
		conversation.refresh_from_db()
		self.assertEqual(conversation.title, "Priority Support")
		self.assertJSONEqual(
			response.content,
			{
				"ok": True,
				"title": "Priority Support",
				"display_title": "Priority Support",
				"uses_custom_title": True,
			},
		)

		response = self.client.post(
			reverse("service_dashboard:rename_conversation", args=[conversation.id]),
			{"title": ""},
			HTTP_X_REQUESTED_WITH="XMLHttpRequest",
		)
		self.assertEqual(response.status_code, 200)
		conversation.refresh_from_db()
		self.assertEqual(conversation.title, "")
		self.assertJSONEqual(
			response.content,
			{
				"ok": True,
				"title": "",
				"display_title": "Rename Peer",
				"uses_custom_title": False,
			},
		)

	def test_dashboard_views_require_role_backed_permissions(self):
		User = get_user_model()
		limited_user = User.objects.create_user(
			username="limiteddash",
			email="limited@example.com",
			password="ComplexPass123!",
		)
		limited_profile = UserProfile.objects.create(
			user=limited_user,
			organization=self.organization,
		)

		self.client.force_login(limited_user)
		self.assertEqual(self.client.get(reverse("service_dashboard:notifications")).status_code, 200)
		self.assertEqual(self.client.get(reverse("service_dashboard:messages")).status_code, 403)
		self.assertEqual(self.client.get(reverse("service_dashboard:calendar")).status_code, 403)

		permission_service = PermissionService(self.organization)
		roles = {role.name: role for role in permission_service.create_default_roles()}
		permission_service.assign_role_to_user(
			user_profile=limited_profile,
			role=roles["Team Member"],
			assigned_by=self.profile,
			skip_permission_check=True,
		)

		self.assertEqual(self.client.get(reverse("service_dashboard:messages")).status_code, 200)
		self.assertEqual(self.client.get(reverse("service_dashboard:calendar")).status_code, 200)
