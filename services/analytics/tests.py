from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from core.models import Organization, UserProfile
from licensing.models import License, LicenseType, Service

User = get_user_model()


class AnalyticsAccessTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.organization = Organization.objects.create(
            name='Test Org',
            organization_type='business',
            is_active=True,
        )

        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
        )

        self.profile = UserProfile.objects.create(
            user=self.user,
            organization=self.organization,
            is_organization_admin=True,
        )

        self.service = Service.objects.create(
            name='Analytics',
            slug='analytics',
            description='Analytics service',
            icon='fas fa-chart-line',
            color='#4f46e5',
            sort_order=3,
            is_active=True,
        )

        self.license_type = LicenseType.objects.create(
            name='basic',
            service=self.service,
            display_name='Basic',
            price_monthly=0,
            price_yearly=0,
            max_users=10,
            max_projects=10,
            max_workflows=100,
            max_storage_gb=10,
            max_api_calls_per_day=1000,
            features=['Analytics'],
            restrictions=[],
            requires_organization=True,
        )

    def _grant_license(self):
        return License.objects.create(
            license_type=self.license_type,
            organization=self.organization,
            account_type='organization',
            status='active',
            billing_cycle='monthly',
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=30),
            current_users=1,
            created_by=self.user,
        )

    def test_index_requires_login(self):
        response = self.client.get('/services/analytics/')
        self.assertEqual(response.status_code, 302)

    def test_index_without_license_shows_no_access(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get('/services/analytics/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'License Required')

    def test_index_with_license_renders_dashboard(self):
        self._grant_license()
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get('/services/analytics/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recent Jobs')

    def test_upload_requires_license(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get('/services/analytics/upload/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'License Required')

    def test_upload_page_with_license(self):
        self._grant_license()
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get('/services/analytics/upload/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Upload Files')