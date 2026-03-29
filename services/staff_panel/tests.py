from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog, Organization, UserProfile
from core.permissions import Role
from services.staff_panel.models import Integration


class StaffPanelBaseTestCase(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username='staffuser',
            email='staff@example.com',
            password='testpass123'
        )
        self.organization = Organization.objects.create(
            name='Acme Org',
            slug='acme-org'
        )
        self.profile = UserProfile.objects.create(
            user=self.user,
            organization=self.organization,
            has_staff_panel_access=True,
            is_organization_admin=False,
            is_active=True,
        )
        self.client.force_login(self.user)


class StaffPanelAccessTests(StaffPanelBaseTestCase):
    def test_dashboard_loads_for_staff_panel_user(self):
        response = self.client.get(reverse('staff_panel:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Staff Panel')

    def test_dashboard_redirects_when_staff_access_removed(self):
        self.profile.has_staff_panel_access = False
        self.profile.save(update_fields=['has_staff_panel_access'])

        response = self.client.get(reverse('staff_panel:dashboard'))
        self.assertEqual(response.status_code, 302)


class StaffPanelLogsExportTests(StaffPanelBaseTestCase):
    def setUp(self):
        super().setUp()
        AuditLog.objects.create(
            user=self.user,
            action='create',
            content_type='Team',
            object_id='1',
            object_repr='Support Team',
            changes={'field': 'value'},
        )

    def test_system_logs_export_csv(self):
        response = self.client.get(reverse('staff_panel:system_logs'), {'export': 'csv'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('attachment; filename=', response['Content-Disposition'])
        self.assertIn('timestamp,user,action,content_type', response.content.decode())

    def test_system_logs_export_json(self):
        response = self.client.get(reverse('staff_panel:system_logs'), {'export': 'json'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]['action'], 'create')


class StaffPanelRoleTests(StaffPanelBaseTestCase):
    def test_create_role_falls_back_to_custom_for_invalid_role_type(self):
        response = self.client.post(
            reverse('staff_panel:create_role'),
            data={
                'role_name': 'Ops Admin',
                'role_description': 'Operations admin role',
                'role_type': 'organization',
                'color': '#336699',
            }
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get('success'))

        role = Role.objects.get(name='Ops Admin', organization=self.organization)
        self.assertEqual(role.role_type, 'custom')


class StaffPanelIntegrationTests(StaffPanelBaseTestCase):
    def test_blocket_integration_test_requires_org_id(self):
        Integration.objects.create(
            organization=self.organization,
            integration_type='blocket',
            name='Acme Blocket',
            config={},
            created_by=self.user,
        )

        response = self.client.post(reverse('staff_panel:test_integration', kwargs={'integration_name': 'blocket'}))
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload.get('success'))
        self.assertIn('not configured', payload.get('message', '').lower())
