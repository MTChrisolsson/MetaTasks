from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import Organization, UserProfile

from .models import SupportTicket


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
