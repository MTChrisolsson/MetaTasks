from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from core.models import Organization, UserProfile

from .models import SupportTag, SupportTemplate, SupportTicket, SupportTicketAuditLog


class SupportTicketAPITests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()

        self.org_a = Organization.objects.create(name='Org A', organization_type='business')
        self.org_b = Organization.objects.create(name='Org B', organization_type='business')

        self.customer_a = self.user_model.objects.create_user(
            username='customer_a',
            email='a@example.com',
            password='ComplexPass123!',
        )
        UserProfile.objects.create(user=self.customer_a, organization=self.org_a)

        self.customer_b = self.user_model.objects.create_user(
            username='customer_b',
            email='b@example.com',
            password='ComplexPass123!',
        )
        UserProfile.objects.create(user=self.customer_b, organization=self.org_b)

        self.agent = self.user_model.objects.create_user(
            username='agent_1',
            email='agent@example.com',
            password='ComplexPass123!',
        )
        UserProfile.objects.create(user=self.agent, organization=self.org_a)
        support_agent_group, _ = Group.objects.get_or_create(name='support_agent')
        self.agent.groups.add(support_agent_group)

        self.admin = self.user_model.objects.create_user(
            username='admin_1',
            email='admin@example.com',
            password='ComplexPass123!',
            is_staff=True,
        )
        UserProfile.objects.create(user=self.admin, organization=self.org_a)

    def test_create_ticket_api_requires_support_tier(self):
        self.client.force_login(self.customer_a)

        forbidden = self.client.post(
            '/api/support/tickets/',
            data={
                'title': 'API-created ticket',
                'description': 'Customer issue from API',
                'category': 'technical_support',
                'priority': 'medium',
                'severity': 'low',
            },
            content_type='application/json',
        )
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_login(self.agent)
        allowed = self.client.post(
            '/api/support/tickets/',
            data={
                'title': 'API-created ticket',
                'description': 'Support issue from API',
                'category': 'technical_support',
                'priority': 'medium',
                'severity': 'low',
            },
            content_type='application/json',
        )

        self.assertEqual(allowed.status_code, 201)
        self.assertEqual(SupportTicket.objects.filter(organization=self.org_a).count(), 1)

    def test_list_is_organization_scoped(self):
        SupportTicket.objects.create(
            organization=self.org_a,
            created_by=self.customer_a,
            title='Org A ticket',
            description='Visible to org A user',
            category='general',
            priority='low',
            severity='low',
        )
        SupportTicket.objects.create(
            organization=self.org_b,
            created_by=self.customer_b,
            title='Org B ticket',
            description='Should not be visible to org A user',
            category='general',
            priority='low',
            severity='low',
        )

        self.client.force_login(self.agent)
        response = self.client.get('/api/support/tickets/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        results = payload.get('results', payload)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'Org A ticket')

    def test_status_endpoint_requires_staff_tier(self):
        ticket = SupportTicket.objects.create(
            organization=self.org_a,
            created_by=self.customer_a,
            title='Status change target',
            description='Needs staff update',
            category='billing',
            priority='medium',
            severity='medium',
        )

        self.client.force_login(self.customer_a)
        forbidden = self.client.patch(
            f'/api/support/tickets/{ticket.ticket_id}/status/',
            data={'status': 'in_progress'},
            content_type='application/json',
        )
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_login(self.agent)
        allowed = self.client.patch(
            f'/api/support/tickets/{ticket.ticket_id}/status/',
            data={'status': 'in_progress'},
            content_type='application/json',
        )
        self.assertEqual(allowed.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'in_progress')

    def test_tag_create_requires_staff_tier(self):
        self.client.force_login(self.customer_a)
        forbidden = self.client.post(
            '/api/support/tags/',
            data={'name': 'Urgent', 'color': '#EF4444'},
            content_type='application/json',
        )
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_login(self.agent)
        allowed = self.client.post(
            '/api/support/tags/',
            data={'name': 'Urgent', 'color': '#EF4444'},
            content_type='application/json',
        )
        self.assertEqual(allowed.status_code, 201)
        self.assertTrue(SupportTag.objects.filter(name='Urgent').exists())

    def test_template_create_requires_staff_tier(self):
        self.client.force_login(self.customer_a)
        forbidden = self.client.post(
            '/api/support/templates/',
            data={
                'name': 'Billing Default',
                'category': 'billing',
                'title_template': 'Billing request',
                'description_template': 'Please provide invoice details.',
                'default_priority': 'medium',
            },
            content_type='application/json',
        )
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_login(self.agent)
        allowed = self.client.post(
            '/api/support/templates/',
            data={
                'name': 'Billing Default',
                'category': 'billing',
                'title_template': 'Billing request',
                'description_template': 'Please provide invoice details.',
                'default_priority': 'medium',
            },
            content_type='application/json',
        )
        self.assertEqual(allowed.status_code, 201)
        self.assertTrue(SupportTemplate.objects.filter(name='Billing Default').exists())

    def test_relationship_create_enforces_same_organization(self):
        ticket_a = SupportTicket.objects.create(
            organization=self.org_a,
            created_by=self.customer_a,
            title='Org A ticket',
            description='Ticket in org A',
            category='general',
            priority='low',
            severity='low',
        )
        ticket_b = SupportTicket.objects.create(
            organization=self.org_b,
            created_by=self.customer_b,
            title='Org B ticket',
            description='Ticket in org B',
            category='general',
            priority='low',
            severity='low',
        )

        self.client.force_login(self.agent)
        response = self.client.post(
            '/api/support/relationships/',
            data={
                'from_ticket': ticket_a.id,
                'to_ticket': ticket_b.id,
                'relationship_type': 'related',
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_audit_logs_are_staff_only_and_org_scoped(self):
        ticket_a = SupportTicket.objects.create(
            organization=self.org_a,
            created_by=self.customer_a,
            title='Audit target A',
            description='Ticket in org A',
            category='general',
            priority='low',
            severity='low',
        )
        ticket_b = SupportTicket.objects.create(
            organization=self.org_b,
            created_by=self.customer_b,
            title='Audit target B',
            description='Ticket in org B',
            category='general',
            priority='low',
            severity='low',
        )
        SupportTicketAuditLog.objects.create(ticket=ticket_a, action='create', performed_by=self.customer_a)
        SupportTicketAuditLog.objects.create(ticket=ticket_b, action='create', performed_by=self.customer_b)

        self.client.force_login(self.customer_a)
        forbidden = self.client.get('/api/support/audit-logs/')
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_login(self.agent)
        allowed = self.client.get('/api/support/audit-logs/')
        self.assertEqual(allowed.status_code, 200)
        payload = allowed.json()
        results = payload.get('results', payload)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['ticket_id'], ticket_a.ticket_id)
