from django.core.management.base import BaseCommand
from django.utils import timezone
from services.analytics.models import StatistikJob
from core.models import Organization


class Command(BaseCommand):
    help = 'Create sample analytics data for testing'

    def handle(self, *args, **options):
        self.stdout.write('Setting up sample analytics data...')
        
        organizations = Organization.objects.filter(is_active=True)[:2]
        
        for org in organizations:
            # Create a sample job
            job, created = StatistikJob.objects.get_or_create(
                organization=org,
                status='completed',
                defaults={
                    'created_by': org.members.first(),
                    'uploaded_at': timezone.now(),
                    'processed_at': timezone.now(),
                    'kpis': {
                        'inventory_24': 150,
                        'published': 120,
                        'published_pct': 80.0,
                        'needs_photos': 30,
                        'missing_citk': 5,
                    },
                    'station_stats': [
                        {'station': 'Station A', 'count': 50, 'pct': 33.3},
                        {'station': 'Station B', 'count': 40, 'pct': 26.7},
                        {'station': 'Station C', 'count': 60, 'pct': 40.0},
                    ]
                }
            )
            
            if created:
                self.stdout.write(f'✓ Created sample analytics job for {org.name}')
            else:
                self.stdout.write(f'✓ Sample analytics job already exists for {org.name}')
        
        self.stdout.write(self.style.SUCCESS('Analytics sample data setup complete!'))