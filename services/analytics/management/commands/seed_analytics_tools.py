from django.core.management.base import BaseCommand, CommandError

from core.models import Organization
from licensing.models import License, Service
from services.analytics.models import AnalyticsTool


DEFAULT_ANALYTICS_TOOLS = [
    {
        'name': 'Lager Statistik Full',
        'slug': 'lager-statistik-full',
        'description': 'CITK, Wayke and inventory processing saved as a job.',
        'icon': 'fas fa-table',
        'action_type': 'named_view',
        'target_view_name': 'analytics:upload',
        'sort_order': 10,
    },
    {
        'name': 'Lager Statistik Lite',
        'slug': 'lager-statistik-lite',
        'description': 'CITK vs Wayke comparison saved as a lite job.',
        'icon': 'fas fa-code-compare',
        'action_type': 'named_view',
        'target_view_name': 'analytics:statistik_lite',
        'sort_order': 20,
    },
]


class Command(BaseCommand):
    help = 'Seed default AnalyticsTool entries for one or more organizations.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--organization-id',
            type=int,
            help='Seed a specific organization by id.',
        )
        parser.add_argument(
            '--organization-slug',
            type=str,
            help='Seed a specific organization by slug.',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Seed all analytics-enabled organizations.',
        )
        parser.add_argument(
            '--include-unlicensed',
            action='store_true',
            help='Include organizations without a valid analytics license.',
        )
        parser.add_argument(
            '--create-demo-org',
            action='store_true',
            help='Create a Demo Organization if no active organization exists.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created/updated without writing changes.',
        )
        parser.add_argument(
            '--force-update',
            action='store_true',
            help='Update existing seeded tools to default values.',
        )

    def handle(self, *args, **options):
        orgs = self._resolve_organizations(options)
        dry_run = options['dry_run']
        force_update = options['force_update']

        created_count = 0
        updated_count = 0
        skipped_count = 0

        for org in orgs:
            self.stdout.write(f'Seeding analytics tools for organization: {org.name} ({org.slug})')
            for tool_data in DEFAULT_ANALYTICS_TOOLS:
                slug = tool_data['slug']
                existing = AnalyticsTool.objects.filter(organization=org, slug=slug).first()

                if existing:
                    if force_update:
                        if dry_run:
                            self.stdout.write(self.style.WARNING(f'  [DRY-RUN] Would update {slug}'))
                        else:
                            for key, value in tool_data.items():
                                setattr(existing, key, value)
                            existing.is_active = True
                            existing.save()
                            self.stdout.write(self.style.WARNING(f'  Updated {slug}'))
                        updated_count += 1
                    else:
                        self.stdout.write(f'  Skipped {slug} (already exists)')
                        skipped_count += 1
                    continue

                if dry_run:
                    self.stdout.write(self.style.SUCCESS(f'  [DRY-RUN] Would create {slug}'))
                    created_count += 1
                    continue

                AnalyticsTool.objects.create(
                    organization=org,
                    name=tool_data['name'],
                    slug=slug,
                    description=tool_data['description'],
                    icon=tool_data['icon'],
                    action_type=tool_data['action_type'],
                    target_view_name=tool_data['target_view_name'],
                    sort_order=tool_data['sort_order'],
                    is_active=True,
                )
                self.stdout.write(self.style.SUCCESS(f'  Created {slug}'))
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Done. Created: {created_count}, Updated: {updated_count}, Skipped: {skipped_count}'
            )
        )

    def _resolve_organizations(self, options):
        org_id = options.get('organization_id')
        org_slug = options.get('organization_slug')
        seed_all = options.get('all')
        create_demo_org = options.get('create_demo_org')
        include_unlicensed = options.get('include_unlicensed')

        selected = [bool(org_id), bool(org_slug), bool(seed_all)]
        if sum(selected) > 1:
            raise CommandError('Use only one of --organization-id, --organization-slug, or --all.')

        if org_id:
            org = Organization.objects.filter(id=org_id).first()
            if not org:
                raise CommandError(f'Organization id={org_id} was not found.')
            return [org]

        if org_slug:
            org = Organization.objects.filter(slug=org_slug).first()
            if not org:
                raise CommandError(f'Organization slug={org_slug} was not found.')
            return [org]

        if seed_all:
            orgs = list(self._get_seed_queryset(include_unlicensed=include_unlicensed))
            if not orgs and create_demo_org:
                orgs = [self._create_demo_org()]
            if not orgs:
                raise CommandError(
                    'No eligible organizations found. Use --create-demo-org or --include-unlicensed.'
                )
            return orgs

        org = self._get_seed_queryset(include_unlicensed=include_unlicensed).order_by('id').first()
        if org:
            return [org]

        if create_demo_org:
            return [self._create_demo_org()]

        raise CommandError(
            'No eligible organizations found. Use --create-demo-org or --include-unlicensed.'
        )

    def _get_seed_queryset(self, *, include_unlicensed=False):
        queryset = Organization.objects.filter(is_active=True)
        if include_unlicensed:
            return queryset

        analytics_service = Service.objects.filter(slug='analytics', is_active=True).first()
        if not analytics_service:
            return Organization.objects.none()

        license_qs = (
            License.objects.filter(
                organization__is_active=True,
                license_type__service=analytics_service,
                status__in=['active', 'trial'],
            )
            .select_related('organization')
            .distinct()
        )

        eligible_org_ids = [license_obj.organization_id for license_obj in license_qs if license_obj.is_valid()]
        if not eligible_org_ids:
            return Organization.objects.none()

        return queryset.filter(id__in=eligible_org_ids)

    def _create_demo_org(self):
        org, created = Organization.objects.get_or_create(
            slug='demo-organization',
            defaults={
                'name': 'Demo Organization',
                'organization_type': 'business',
                'description': 'Auto-created demo organization for analytics tool seeding.',
                'is_active': True,
            },
        )

        if created:
            self.stdout.write(self.style.SUCCESS('Created Demo Organization (slug=demo-organization).'))
        else:
            if not org.is_active:
                org.is_active = True
                org.save(update_fields=['is_active'])
            self.stdout.write('Using existing Demo Organization (slug=demo-organization).')

        return org
