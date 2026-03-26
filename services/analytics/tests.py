from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from core.models import Organization, UserProfile
from licensing.models import License, LicenseType, Service
from services.analytics.models import AnalyticsTool, StatistikJob, VehicleRecord

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

    def _create_tool(self, *, name, slug, target_view_name):
        return AnalyticsTool.objects.create(
            organization=self.organization,
            created_by=self.profile,
            name=name,
            slug=slug,
            description=f'{name} tool',
            icon='fas fa-tools',
            action_type='named_view',
            target_view_name=target_view_name,
            is_active=True,
        )

    def _seed_analytics_records(self):
        job = StatistikJob.objects.create(
            organization=self.organization,
            created_by=self.profile,
            status='completed',
            processed_at=timezone.now(),
            wayke_file='analytics/wayke/test.csv',
            citk_file='analytics/citk/test.xlsx',
        )

        VehicleRecord.objects.create(
            job=job,
            registration='ABC123',
            model='Model A',
            status=10,
            current_station='Station 1',
            is_published=True,
            is_photographed=True,
            missing_citk=False,
            needs_photos=False,
            days_in_stock=20,
            published_price=100000,
        )
        VehicleRecord.objects.create(
            job=job,
            registration='DEF456',
            model='Model B',
            status=20,
            current_station='Station 1',
            is_published=False,
            is_photographed=False,
            missing_citk=True,
            needs_photos=True,
            days_in_stock=45,
            published_price=None,
        )
        return job

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
        self._create_tool(
            name='Lager Statistik Full',
            slug='lager-statistik-full',
            target_view_name='analytics:upload',
        )
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get('/services/analytics/upload/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Upload Files')

    def test_upload_page_without_tool_returns_404(self):
        self._grant_license()
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get('/services/analytics/upload/')
        self.assertEqual(response.status_code, 404)

    def test_statistik_lite_requires_enabled_tool(self):
        self._grant_license()
        self.client.login(username='testuser', password='testpass123')

        no_tool_response = self.client.get('/services/analytics/statistik-lite/')
        self.assertEqual(no_tool_response.status_code, 404)

        self._create_tool(
            name='Lager Statistik Lite',
            slug='lager-statistik-lite',
            target_view_name='analytics:statistik_lite',
        )
        with_tool_response = self.client.get('/services/analytics/statistik-lite/')
        self.assertEqual(with_tool_response.status_code, 200)
        self.assertContains(with_tool_response, 'Lager Statistik Lite')

    def test_universal_tool_pages_render_with_license(self):
        self._grant_license()
        self._seed_analytics_records()
        self.client.login(username='testuser', password='testpass123')

        pages = [
            ('/services/analytics/data-health-monitor/', 'Data Health Monitor'),
            ('/services/analytics/kpi-builder/', 'KPI Builder'),
            ('/services/analytics/alert-center/', 'Alert Center'),
            ('/services/analytics/scheduled-reports/', 'Scheduled Report Builder'),
        ]
        for path, marker in pages:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, marker)

    def test_scheduled_report_export_returns_csv(self):
        self._grant_license()
        self._seed_analytics_records()
        self.client.login(username='testuser', password='testpass123')

        response = self.client.get('/services/analytics/scheduled-reports/export/?report_type=jobs_summary&days=30')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response['Content-Type'])
        self.assertIn('attachment;', response['Content-Disposition'])

    def test_kpi_builder_renders_metric_value(self):
        self._grant_license()
        self._seed_analytics_records()
        self.client.login(username='testuser', password='testpass123')

        response = self.client.get('/services/analytics/kpi-builder/?metric=total_vehicles&days=30')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Total Vehicles')