from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone

from core.models import Notification, Organization, UserProfile

from .models import SupportTicket
from .tasks import auto_close_resolved_tickets, monitor_sla_deadlines


class SupportTicketModelTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username='supportuser',
            email='support@example.com',
            password='ComplexPass123!',
            first_name='Support',
            last_name='Agent',
        )
        self.organization = Organization.objects.create(
            name='Acme Support Org',
            organization_type='business',
        )
        UserProfile.objects.create(user=self.user, organization=self.organization)

    def test_ticket_id_is_generated_with_prefix(self):
        ticket = SupportTicket.objects.create(
            organization=self.organization,
            created_by=self.user,
            title='Unable to log in',
            description='Customer cannot access account after reset.',
            category='technical_support',
            priority='high',
            severity='medium',
        )

        self.assertTrue(ticket.ticket_id.startswith('TKT-'))

    def test_status_transition_sets_resolved_and_closed_timestamps(self):
        ticket = SupportTicket.objects.create(
            organization=self.organization,
            created_by=self.user,
            title='Billing mismatch',
            description='Invoice amount is incorrect.',
            category='billing',
            priority='medium',
            severity='low',
        )

        ticket.status = 'resolved'
        ticket.save()
        self.assertIsNotNone(ticket.resolved_at)

        ticket.status = 'closed'
        ticket.save()
        self.assertIsNotNone(ticket.closed_at)


class SupportTaskTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.organization = Organization.objects.create(
            name='Task Test Org',
            organization_type='business',
        )
        self.customer = self.user_model.objects.create_user(
            username='task_customer',
            email='task_customer@example.com',
            password='ComplexPass123!',
        )
        UserProfile.objects.create(user=self.customer, organization=self.organization)

        self.agent = self.user_model.objects.create_user(
            username='task_agent',
            email='task_agent@example.com',
            password='ComplexPass123!',
        )
        UserProfile.objects.create(user=self.agent, organization=self.organization)
        support_agent_group, _ = Group.objects.get_or_create(name='support_agent')
        self.agent.groups.add(support_agent_group)

    def test_monitor_sla_deadlines_notifies_support_agents_when_unassigned(self):
        ticket = SupportTicket.objects.create(
            organization=self.organization,
            created_by=self.customer,
            title='Unassigned SLA breach',
            description='Breach should notify fallback support agents',
            category='technical_support',
            priority='high',
            severity='high',
            status='open',
            sla_deadline=timezone.now() - timedelta(hours=2),
        )

        monitor_sla_deadlines()

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.agent,
                content_type='SupportTicket',
                object_id=str(ticket.pk),
                title=f'SLA Breached: {ticket.ticket_id}',
            ).exists()
        )

    def test_auto_close_resolved_tickets_sets_closed_status(self):
        old_resolved = SupportTicket.objects.create(
            organization=self.organization,
            created_by=self.customer,
            title='Resolved old ticket',
            description='Should be auto-closed',
            category='general',
            priority='medium',
            severity='low',
            status='resolved',
            resolved_at=timezone.now() - timedelta(days=20),
        )

        auto_close_resolved_tickets()

        old_resolved.refresh_from_db()
        self.assertEqual(old_resolved.status, 'closed')
        self.assertIsNotNone(old_resolved.closed_at)


class SupportAccessControlTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.organization = Organization.objects.create(
            name='Access Test Org',
            organization_type='business',
        )

        self.customer = self.user_model.objects.create_user(
            username='access_customer',
            email='access_customer@example.com',
            password='ComplexPass123!',
        )
        UserProfile.objects.create(user=self.customer, organization=self.organization)

        self.agent = self.user_model.objects.create_user(
            username='access_agent',
            email='access_agent@example.com',
            password='ComplexPass123!',
        )
        UserProfile.objects.create(user=self.agent, organization=self.organization)
        support_agent_group, _ = Group.objects.get_or_create(name='support_agent')
        self.agent.groups.add(support_agent_group)

    def test_customer_cannot_access_support_dashboard_root(self):
        self.client.force_login(self.customer)
        response = self.client.get('/customer-support/')
        self.assertEqual(response.status_code, 302)

    def test_support_agent_can_access_support_dashboard_root(self):
        self.client.force_login(self.agent)
        response = self.client.get('/customer-support/')
        self.assertEqual(response.status_code, 200)

    def test_customer_can_still_access_self_service_portal(self):
        self.client.force_login(self.customer)
        response = self.client.get('/customer-support/portal/')
        self.assertEqual(response.status_code, 200)
