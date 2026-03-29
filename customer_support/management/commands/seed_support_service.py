"""
Management command: seed_support_service

Registers the customer_support service and license types in the licensing
system, and seeds default KB categories for every organisation that doesn't
already have them.

Usage:
    python manage.py seed_support_service
    python manage.py seed_support_service --org-id 3   # seed a specific org
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils.text import slugify


class Command(BaseCommand):
    help = 'Seed the Customer Support service, license types, and default KB categories'

    def add_arguments(self, parser):
        parser.add_argument(
            '--org-id',
            type=int,
            default=None,
            dest='org_id',
            help='Seed KB categories only for this organisation ID',
        )

    def handle(self, *args, **options):
        self._seed_service()
        self._seed_license_types()
        self._seed_kb_categories(options['org_id'])
        self.stdout.write(self.style.SUCCESS('Customer support service seeded successfully.'))

    # ------------------------------------------------------------------ #

    def _seed_service(self):
        from licensing.models import Service

        service, created = Service.objects.get_or_create(
            slug='customer_support',
            defaults={
                'name': 'Customer Support',
                'description': 'Customer support ticket management and knowledge base',
                'icon': 'fas fa-headset',
                'color': '#0EA5E9',
                'sort_order': 6,
                'is_active': True,
            },
        )
        verb = 'Created' if created else 'Already exists'
        self.stdout.write(f'{verb}: Service "{service.name}"')

    def _seed_license_types(self):
        from licensing.models import LicenseType, Service

        service = Service.objects.get(slug='customer_support')
        tiers = [
            ('free', 'Free', 0, {'tickets_per_month': 5, 'agents': 1, 'kb_articles': 10}),
            ('starter', 'Starter', 29, {'tickets_per_month': 100, 'agents': 3, 'kb_articles': 50}),
            ('professional', 'Professional', 99, {'tickets_per_month': 1000, 'agents': 10, 'kb_articles': 500}),
            ('enterprise', 'Enterprise', 499, {'tickets_per_month': None, 'agents': None, 'kb_articles': None}),
        ]
        for name, display_name, price, features in tiers:
            lt, created = LicenseType.objects.get_or_create(
                service=service,
                name=name,
                defaults={
                    'display_name': display_name,
                    'price_monthly': price,
                    'features': features,
                    'is_active': True,
                },
            )
            verb = 'Created' if created else 'Already exists'
            self.stdout.write(f'  {verb}: LicenseType "{lt.display_name}"')

    def _seed_kb_categories(self, org_id=None):
        from core.models import Organization
        from customer_support.models import KBCategory

        kb_table_name = KBCategory._meta.db_table
        if kb_table_name not in connection.introspection.table_names():
            self.stdout.write(
                self.style.WARNING(
                    'Skipping KB category seeding: KB tables are not migrated yet. '
                    'Run "python manage.py migrate" and re-run this command.'
                )
            )
            return

        default_categories = [
            ('Getting Started', 'getting-started', 'fa-rocket', 'Guides for new users'),
            ('Billing & Payments', 'billing-payments', 'fa-credit-card', 'Billing questions and invoices'),
            ('Technical Support', 'technical-support', 'fa-tools', 'Troubleshooting and technical help'),
            ('Features & How-To', 'features-how-to', 'fa-lightbulb', 'How to use features'),
            ('Policies & Legal', 'policies-legal', 'fa-gavel', 'Terms, privacy, and policies'),
        ]

        orgs = Organization.objects.all()
        if org_id:
            orgs = orgs.filter(pk=org_id)
            if not orgs.exists():
                raise CommandError(f'Organisation with id={org_id} not found.')

        for org in orgs:
            for i, (name, slug_base, icon, description) in enumerate(default_categories):
                slug = slug_base
                KBCategory.objects.get_or_create(
                    organization=org,
                    slug=slug,
                    defaults={
                        'name': name,
                        'icon': icon,
                        'description': description,
                        'sort_order': i,
                    },
                )
            self.stdout.write(f'  KB categories seeded for org: {org.name}')
