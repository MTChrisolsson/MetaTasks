from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Organization
from licensing.models import License, LicenseType, Service, UserLicenseAssignment
from licensing.services import LicensingService


class Command(BaseCommand):
    help = 'Create the inventory service catalog entry, inventory license types, and optionally an organization license.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--org-slug',
            help='Optional organization slug. If provided, an inventory license is created for the organization.',
        )
        parser.add_argument(
            '--license-type',
            choices=['personal_free', 'basic', 'professional', 'enterprise'],
            default='basic',
            help='License type to create for the organization when --org-slug is provided.',
        )
        parser.add_argument(
            '--trial-days',
            type=int,
            default=30,
            help='Trial length in days when --license-type professional is created as a trial.',
        )
        parser.add_argument(
            '--assign-admin',
            action='store_true',
            help='Assign the created organization license to the first active organization admin.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        service = self._ensure_inventory_service()
        license_types = self._ensure_inventory_license_types(service)

        self.stdout.write(self.style.SUCCESS('Inventory service is ready.'))
        for license_type in license_types:
            self.stdout.write(
                f" - {license_type.display_name} ({license_type.name})"
            )

        org_slug = options.get('org_slug')
        if not org_slug:
            return

        organization = Organization.objects.filter(slug=org_slug).first()
        if not organization:
            raise CommandError(f'Organization with slug "{org_slug}" was not found.')

        selected_type = next(
            (license_type for license_type in license_types if license_type.name == options['license_type']),
            None,
        )
        if selected_type is None:
            raise CommandError('Selected inventory license type could not be resolved.')

        now = timezone.now()
        defaults = {
            'status': 'trial' if selected_type.name == 'professional' else 'active',
            'billing_cycle': 'monthly',
            'start_date': now,
            'end_date': now + timedelta(days=365),
        }
        if selected_type.name == 'professional':
            defaults['trial_end_date'] = now + timedelta(days=options['trial_days'])

        license_obj, created = License.objects.get_or_create(
            organization=organization,
            license_type=selected_type,
            defaults=defaults,
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Created {selected_type.display_name} inventory license for {organization.name}.'
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f'{organization.name} already has an inventory {selected_type.display_name} license.'
                )
            )

        if options.get('assign_admin'):
            admin_profile = organization.members.filter(is_active=True, is_organization_admin=True).select_related('user').first()
            if not admin_profile:
                self.stdout.write(self.style.WARNING('No active organization admin found to assign the license.'))
                return

            existing_assignment = UserLicenseAssignment.objects.filter(
                license=license_obj,
                user_profile=admin_profile,
                is_active=True,
            ).exists()
            if existing_assignment:
                self.stdout.write(self.style.WARNING('Inventory license was already assigned to the organization admin.'))
                return

            success, result = LicensingService.assign_user_to_license(
                license_obj,
                admin_profile,
                admin_profile.user,
            )
            if not success:
                raise CommandError(str(result))

            self.stdout.write(
                self.style.SUCCESS(
                    f'Assigned inventory license to {admin_profile.user.get_username()}.'
                )
            )

    def _ensure_inventory_service(self):
        service, created = Service.objects.get_or_create(
            slug='inventory',
            defaults={
                'name': 'Inventory',
                'description': 'Configurable inventory and stock management service',
                'version': '1.0.0',
                'is_active': True,
                'icon': 'fas fa-boxes-stacked',
                'color': '#b45309',
                'sort_order': 4,
                'allows_personal_free': True,
                'personal_free_limits': {
                    'users': 1,
                    'items': 50,
                    'locations': 2,
                    'movements_per_month': 200,
                },
            },
        )

        if not created:
            service.name = 'Inventory'
            service.description = 'Configurable inventory and stock management service'
            service.version = '1.0.0'
            service.is_active = True
            service.icon = 'fas fa-boxes-stacked'
            service.color = '#b45309'
            service.sort_order = 4
            service.allows_personal_free = True
            service.personal_free_limits = {
                'users': 1,
                'items': 50,
                'locations': 2,
                'movements_per_month': 200,
            }
            service.save()

        return service

    def _ensure_inventory_license_types(self, service):
        license_type_data = [
            {
                'name': 'personal_free',
                'display_name': 'Personal Free',
                'price_monthly': Decimal('0.00'),
                'price_yearly': Decimal('0.00'),
                'max_users': 1,
                'max_projects': 1,
                'max_workflows': 10,
                'max_storage_gb': 1,
                'max_api_calls_per_day': 250,
                'features': ['Single-user stock tracking', 'Two locations', 'Basic movement history'],
                'restrictions': ['No team assignment', 'Limited imports'],
                'is_personal_only': True,
                'requires_organization': False,
            },
            {
                'name': 'basic',
                'display_name': 'Basic Team',
                'price_monthly': Decimal('39.00'),
                'price_yearly': Decimal('390.00'),
                'max_users': 10,
                'max_projects': 5,
                'max_workflows': 50,
                'max_storage_gb': 10,
                'max_api_calls_per_day': 1500,
                'features': ['Multi-location stock', 'Custom fields', 'Low-stock alerts', 'CSV import/export'],
                'restrictions': ['Limited approval workflows'],
                'is_personal_only': False,
                'requires_organization': True,
            },
            {
                'name': 'professional',
                'display_name': 'Professional',
                'price_monthly': Decimal('99.00'),
                'price_yearly': Decimal('990.00'),
                'max_users': 50,
                'max_projects': 25,
                'max_workflows': 250,
                'max_storage_gb': 100,
                'max_api_calls_per_day': 10000,
                'features': ['Approval workflows', 'CFlows integration', 'Advanced imports', 'API access'],
                'restrictions': [],
                'is_personal_only': False,
                'requires_organization': True,
            },
            {
                'name': 'enterprise',
                'display_name': 'Enterprise',
                'price_monthly': Decimal('299.00'),
                'price_yearly': Decimal('2990.00'),
                'max_users': None,
                'max_projects': None,
                'max_workflows': None,
                'max_storage_gb': None,
                'max_api_calls_per_day': None,
                'features': ['Unlimited inventory scale', 'Custom integrations', 'Advanced support'],
                'restrictions': [],
                'is_personal_only': False,
                'requires_organization': True,
            },
        ]

        license_types = []
        for data in license_type_data:
            license_type, _ = LicenseType.objects.get_or_create(
                service=service,
                name=data['name'],
                defaults=data,
            )
            license_types.append(license_type)

        return license_types
