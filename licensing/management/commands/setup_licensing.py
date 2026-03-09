from django.core.management.base import BaseCommand
from django.utils import timezone
from decimal import Decimal
from licensing.models import Service, LicenseType, License
from core.models import Organization


class Command(BaseCommand):
    help = 'Set up initial licensing data for MetaTask services'

    def handle(self, *args, **options):
        self.stdout.write('Setting up initial licensing data...')
        
        # Create CFlows service
        cflows_service, created = Service.objects.get_or_create(
            slug='cflows',
            defaults={
                'name': 'CFlows',
                'description': 'Workflow Management System',
                'version': '1.0.0',
                'is_active': True,
                'icon': 'fas fa-project-diagram',
                'color': '#2563eb',
                'sort_order': 1,
                'allows_personal_free': True,
                'personal_free_limits': {
                    'users': 1,
                    'workflows': 3,
                    'work_items': 100,
                    'projects': 2
                }
            }
        )
        
        if created:
            self.stdout.write(f'✓ Created CFlows service')
        else:
            # Update existing service with missing fields
            cflows_service.icon = 'fas fa-project-diagram'
            cflows_service.color = '#2563eb'
            cflows_service.sort_order = 1
            cflows_service.save()
            self.stdout.write(f'✓ Updated CFlows service')
        
        # Create Scheduling service
        scheduling_service, created = Service.objects.get_or_create(
            slug='scheduling',
            defaults={
                'name': 'Scheduling',
                'description': 'Resource Allocation and Scheduling System',
                'version': '1.0.0',
                'is_active': True,  # Now available
                'icon': 'fas fa-calendar-alt',
                'color': '#059669',
                'sort_order': 2,
                'allows_personal_free': True,
                'personal_free_limits': {
                    'users': 1,
                    'projects': 2,
                    'resources': 5,
                    'events': 20
                }
            }
        )
        
        if created:
            self.stdout.write(f'✓ Created Scheduling service')
        else:
            # Update existing service with missing fields
            scheduling_service.icon = 'fas fa-calendar-alt'
            scheduling_service.color = '#059669'
            scheduling_service.sort_order = 2
            scheduling_service.is_active = True  # Make sure it's active
            scheduling_service.personal_free_limits = {
                'users': 1,
                'projects': 2,
                'resources': 5,
                'events': 20
            }
            scheduling_service.save()
            self.stdout.write(f'✓ Updated Scheduling service')

        # Create Analytics service
        analytics_service, created = Service.objects.get_or_create(
            slug='analytics',
            defaults={
                'name': 'Analytics',
                'description': 'Vehicle inventory analytics and KPI processing',
                'version': '1.0.0',
                'is_active': True,
                'icon': 'fas fa-chart-line',
                'color': '#4f46e5',
                'sort_order': 3,
                'allows_personal_free': True,
                'personal_free_limits': {
                    'users': 1,
                    'projects': 1,
                    'workflows': 5,
                    'storage_gb': 1,
                },
            },
        )

        if created:
            self.stdout.write('✓ Created Analytics service')
        else:
            analytics_service.icon = 'fas fa-chart-line'
            analytics_service.color = '#4f46e5'
            analytics_service.sort_order = 3
            analytics_service.is_active = True
            analytics_service.personal_free_limits = {
                'users': 1,
                'projects': 1,
                'workflows': 5,
                'storage_gb': 1,
            }
            analytics_service.save()
            self.stdout.write('✓ Updated Analytics service')
        
        # Create license types for CFlows
        license_types_data = [
            {
                'name': 'personal_free',
                'display_name': 'Personal Free',
                'price_monthly': Decimal('0.00'),
                'price_yearly': Decimal('0.00'),
                'max_users': 1,
                'max_projects': 2,
                'max_workflows': 3,
                'max_storage_gb': 1,
                'max_api_calls_per_day': 100,
                'features': ['Basic workflows', 'Personal workspace', 'Email notifications'],
                'restrictions': ['No team collaboration', 'Limited integrations'],
                'is_personal_only': True,
                'requires_organization': False
            },
            {
                'name': 'basic',
                'display_name': 'Basic Team',
                'price_monthly': Decimal('29.00'),
                'price_yearly': Decimal('290.00'),
                'max_users': 10,
                'max_projects': 10,
                'max_workflows': 25,
                'max_storage_gb': 10,
                'max_api_calls_per_day': 1000,
                'features': ['Team collaboration', 'Custom workflows', 'Basic integrations', 'Email & SMS notifications'],
                'restrictions': ['Limited admin features'],
                'is_personal_only': False,
                'requires_organization': True
            },
            {
                'name': 'professional',
                'display_name': 'Professional',
                'price_monthly': Decimal('79.00'),
                'price_yearly': Decimal('790.00'),
                'max_users': 50,
                'max_projects': 50,
                'max_workflows': 100,
                'max_storage_gb': 100,
                'max_api_calls_per_day': 10000,
                'features': ['Advanced workflows', 'All integrations', 'Advanced analytics', 'Priority support'],
                'restrictions': [],
                'is_personal_only': False,
                'requires_organization': True
            },
            {
                'name': 'enterprise',
                'display_name': 'Enterprise',
                'price_monthly': Decimal('299.00'),
                'price_yearly': Decimal('2990.00'),
                'max_users': None,  # Unlimited
                'max_projects': None,
                'max_workflows': None,
                'max_storage_gb': None,
                'max_api_calls_per_day': None,
                'features': ['Unlimited everything', 'Custom integrations', 'Dedicated support', 'SLA guarantee'],
                'restrictions': [],
                'is_personal_only': False,
                'requires_organization': True
            }
        ]
        
        for lt_data in license_types_data:
            license_type, created = LicenseType.objects.get_or_create(
                service=cflows_service,
                name=lt_data['name'],
                defaults=lt_data
            )
            
            if created:
                self.stdout.write(f'✓ Created CFlows license type: {lt_data["display_name"]}')
            else:
                self.stdout.write(f'✓ CFlows license type already exists: {lt_data["display_name"]}')
        
        # Create license types for Scheduling
        scheduling_license_types_data = [
            {
                'name': 'personal_free',
                'display_name': 'Personal Free',
                'price_monthly': Decimal('0.00'),
                'price_yearly': Decimal('0.00'),
                'max_users': 1,
                'max_projects': 2,
                'max_workflows': 5,  # Using max_workflows for events/bookings
                'max_storage_gb': 1,
                'max_api_calls_per_day': 100,
                'features': ['Basic scheduling', 'Personal calendar', 'Resource management', 'Event notifications'],
                'restrictions': ['No team collaboration', 'Limited integrations'],
                'is_personal_only': True,
                'requires_organization': False
            },
            {
                'name': 'basic',
                'display_name': 'Basic Team',
                'price_monthly': Decimal('19.00'),
                'price_yearly': Decimal('190.00'),
                'max_users': 10,
                'max_projects': 10,
                'max_workflows': 50,  # Using max_workflows for events/bookings
                'max_storage_gb': 10,
                'max_api_calls_per_day': 1000,
                'features': ['Team scheduling', 'Resource booking', 'Calendar sharing', 'Basic analytics'],
                'restrictions': ['Limited advanced features'],
                'is_personal_only': False,
                'requires_organization': True
            },
            {
                'name': 'professional',
                'display_name': 'Professional',
                'price_monthly': Decimal('49.00'),
                'price_yearly': Decimal('490.00'),
                'max_users': 50,
                'max_projects': 50,
                'max_workflows': 200,  # Using max_workflows for events/bookings
                'max_storage_gb': 100,
                'max_api_calls_per_day': 10000,
                'features': ['Advanced scheduling', 'Resource optimization', 'Advanced analytics', 'Integrations'],
                'restrictions': [],
                'is_personal_only': False,
                'requires_organization': True
            },
            {
                'name': 'enterprise',
                'display_name': 'Enterprise',
                'price_monthly': Decimal('199.00'),
                'price_yearly': Decimal('1990.00'),
                'max_users': None,  # Unlimited
                'max_projects': None,
                'max_workflows': None,  # Unlimited events/bookings
                'max_storage_gb': None,
                'max_api_calls_per_day': None,
                'features': ['Unlimited scheduling', 'Custom integrations', 'Dedicated support', 'SLA guarantee'],
                'restrictions': [],
                'is_personal_only': False,
                'requires_organization': True
            }
        ]
        
        for lt_data in scheduling_license_types_data:
            license_type, created = LicenseType.objects.get_or_create(
                service=scheduling_service,
                name=lt_data['name'],
                defaults=lt_data
            )
            
            if created:
                self.stdout.write(f'✓ Created Scheduling license type: {lt_data["display_name"]}')
            else:
                self.stdout.write(f'✓ Scheduling license type already exists: {lt_data["display_name"]}')

        # Create license types for Analytics
        analytics_license_types_data = [
            {
                'name': 'personal_free',
                'display_name': 'Personal Free',
                'price_monthly': Decimal('0.00'),
                'price_yearly': Decimal('0.00'),
                'max_users': 1,
                'max_projects': 1,
                'max_workflows': 10,
                'max_storage_gb': 1,
                'max_api_calls_per_day': 100,
                'features': ['Basic KPI dashboards', 'Single-user uploads', 'Recent job history'],
                'restrictions': ['No advanced exports', 'Limited history depth'],
                'is_personal_only': True,
                'requires_organization': False,
            },
            {
                'name': 'basic',
                'display_name': 'Basic Team',
                'price_monthly': Decimal('19.00'),
                'price_yearly': Decimal('190.00'),
                'max_users': 10,
                'max_projects': 10,
                'max_workflows': 100,
                'max_storage_gb': 10,
                'max_api_calls_per_day': 1000,
                'features': ['Team analytics access', 'Station KPI breakdown', 'Job history'],
                'restrictions': ['Limited automation'],
                'is_personal_only': False,
                'requires_organization': True,
            },
            {
                'name': 'professional',
                'display_name': 'Professional',
                'price_monthly': Decimal('59.00'),
                'price_yearly': Decimal('590.00'),
                'max_users': 50,
                'max_projects': 50,
                'max_workflows': 500,
                'max_storage_gb': 100,
                'max_api_calls_per_day': 10000,
                'features': ['Advanced analytics', 'Large file support', 'Priority processing'],
                'restrictions': [],
                'is_personal_only': False,
                'requires_organization': True,
            },
            {
                'name': 'enterprise',
                'display_name': 'Enterprise',
                'price_monthly': Decimal('199.00'),
                'price_yearly': Decimal('1990.00'),
                'max_users': None,
                'max_projects': None,
                'max_workflows': None,
                'max_storage_gb': None,
                'max_api_calls_per_day': None,
                'features': ['Unlimited analytics', 'Custom integrations', 'Dedicated support'],
                'restrictions': [],
                'is_personal_only': False,
                'requires_organization': True,
            },
        ]

        for lt_data in analytics_license_types_data:
            license_type, created = LicenseType.objects.get_or_create(
                service=analytics_service,
                name=lt_data['name'],
                defaults=lt_data,
            )

            if created:
                self.stdout.write(f'✓ Created Analytics license type: {lt_data["display_name"]}')
            else:
                self.stdout.write(f'✓ Analytics license type already exists: {lt_data["display_name"]}')
        
        # Set up personal free licenses for personal organizations
        personal_orgs = Organization.objects.filter(organization_type='personal')
        
        # CFlows personal free licenses
        cflows_personal_free_license_type = LicenseType.objects.get(
            service=cflows_service, 
            name='personal_free'
        )
        
        # Scheduling personal free licenses  
        scheduling_personal_free_license_type = LicenseType.objects.get(
            service=scheduling_service,
            name='personal_free'
        )

        # Analytics personal free licenses
        analytics_personal_free_license_type = LicenseType.objects.get(
            service=analytics_service,
            name='personal_free'
        )
        
        for org in personal_orgs:
            # Create CFlows license
            cflows_license, created = License.objects.get_or_create(
                organization=org,
                license_type=cflows_personal_free_license_type,
                defaults={
                    'account_type': 'personal',
                    'is_personal_free': True,
                    'status': 'active',
                    'billing_cycle': 'lifetime',
                    'start_date': timezone.now(),
                    'current_users': org.members.count(),
                }
            )
            
            if created:
                self.stdout.write(f'✓ Created CFlows personal free license for: {org.name}')
            
            # Create Scheduling license
            scheduling_license, created = License.objects.get_or_create(
                organization=org,
                license_type=scheduling_personal_free_license_type,
                defaults={
                    'account_type': 'personal',
                    'is_personal_free': True,
                    'status': 'active',
                    'billing_cycle': 'lifetime',
                    'start_date': timezone.now(),
                    'current_users': org.members.count(),
                }
            )
            
            if created:
                self.stdout.write(f'✓ Created Scheduling personal free license for: {org.name}')

            # Create Analytics license
            analytics_license, created = License.objects.get_or_create(
                organization=org,
                license_type=analytics_personal_free_license_type,
                defaults={
                    'account_type': 'personal',
                    'is_personal_free': True,
                    'status': 'active',
                    'billing_cycle': 'lifetime',
                    'start_date': timezone.now(),
                    'current_users': org.members.count(),
                }
            )

            if created:
                self.stdout.write(f'✓ Created Analytics personal free license for: {org.name}')
        
        # Update existing Demo Car Dealership organization to be business type with basic license
        try:
            demo_org = Organization.objects.get(name='Demo Car Dealership')
            if demo_org.organization_type != 'business':
                demo_org.organization_type = 'business'
                demo_org.save()
                self.stdout.write(f'✓ Updated {demo_org.name} to business organization')
            
            # CFlows basic license
            cflows_basic_license_type = LicenseType.objects.get(
                service=cflows_service,
                name='basic'
            )
            
            cflows_license, created = License.objects.get_or_create(
                organization=demo_org,
                license_type=cflows_basic_license_type,
                defaults={
                    'account_type': 'organization',
                    'is_personal_free': False,
                    'status': 'trial',
                    'billing_cycle': 'monthly',
                    'start_date': timezone.now(),
                    'trial_end_date': timezone.now() + timezone.timedelta(days=30),
                    'current_users': demo_org.members.count(),
                    'current_workflows': demo_org.workflows.count() if hasattr(demo_org, 'workflows') else 0,
                }
            )
            
            if created:
                self.stdout.write(f'✓ Created CFlows basic trial license for: {demo_org.name}')
            
            # Scheduling basic license
            scheduling_basic_license_type = LicenseType.objects.get(
                service=scheduling_service,
                name='basic'
            )
            
            scheduling_license, created = License.objects.get_or_create(
                organization=demo_org,
                license_type=scheduling_basic_license_type,
                defaults={
                    'account_type': 'organization',
                    'is_personal_free': False,
                    'status': 'trial',
                    'billing_cycle': 'monthly',
                    'start_date': timezone.now(),
                    'trial_end_date': timezone.now() + timezone.timedelta(days=30),
                    'current_users': demo_org.members.count(),
                    'current_projects': 0,  # Will be updated as projects are created
                    'current_workflows': 0,  # Using workflows field for events/bookings tracking
                }
            )
            
            if created:
                self.stdout.write(f'✓ Created Scheduling basic trial license for: {demo_org.name}')

            # Analytics basic license
            analytics_basic_license_type = LicenseType.objects.get(
                service=analytics_service,
                name='basic'
            )

            analytics_license, created = License.objects.get_or_create(
                organization=demo_org,
                license_type=analytics_basic_license_type,
                defaults={
                    'account_type': 'organization',
                    'is_personal_free': False,
                    'status': 'trial',
                    'billing_cycle': 'monthly',
                    'start_date': timezone.now(),
                    'trial_end_date': timezone.now() + timezone.timedelta(days=30),
                    'current_users': demo_org.members.count(),
                    'current_projects': 0,
                    'current_workflows': 0,
                }
            )

            if created:
                self.stdout.write(f'✓ Created Analytics basic trial license for: {demo_org.name}')
                
        except Organization.DoesNotExist:
            self.stdout.write('⚠ Demo Car Dealership organization not found')
        
        self.stdout.write(
            self.style.SUCCESS('Successfully set up initial licensing data!')
        )
