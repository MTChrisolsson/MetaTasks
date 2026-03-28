from decimal import Decimal

from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Organization, UserProfile
from licensing.models import License, LicenseType, Service, UserLicenseAssignment
from .models import InventoryItem, InventoryLocation, ItemStock, MovementReason
from .services import InventoryService


class InventoryServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='inventory-user', password='testpass123')
        self.organization = Organization.objects.create(name='Inventory Org')
        UserProfile.objects.create(user=self.user, organization=self.organization)

        self.item = InventoryItem.objects.create(
            organization=self.organization,
            sku='WHEEL-001',
            name='Wheel Set',
            unit='set',
        )
        self.source = InventoryLocation.objects.create(
            organization=self.organization,
            name='Main Warehouse',
            code='MAIN',
        )
        self.target = InventoryLocation.objects.create(
            organization=self.organization,
            name='Vehicle Bay',
            code='BAY-01',
        )
        self.service = InventoryService(self.organization)

    def test_transfer_movement_updates_both_locations(self):
        self.service.record_movement(
            item=self.item,
            movement_type='in',
            quantity=Decimal('10'),
            user=self.user,
            target_location=self.source,
        )

        self.service.record_movement(
            item=self.item,
            movement_type='transfer',
            quantity=Decimal('4'),
            user=self.user,
            source_location=self.source,
            target_location=self.target,
        )

        source_stock = self.item.stock_levels.get(location=self.source)
        target_stock = self.item.stock_levels.get(location=self.target)

        self.assertEqual(source_stock.quantity, Decimal('6'))
        self.assertEqual(target_stock.quantity, Decimal('4'))


class InventoryAccessTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='licensed-user', password='testpass123')
        self.organization = Organization.objects.create(name='Licensed Org')
        self.profile = UserProfile.objects.create(
            user=self.user,
            organization=self.organization,
            is_organization_admin=True,
        )

        self.service = Service.objects.create(
            name='Inventory',
            slug='inventory',
            description='Inventory service',
            is_active=True,
        )
        self.license_type = LicenseType.objects.create(
            service=self.service,
            name='basic',
            display_name='Basic Team',
            requires_organization=True,
        )
        self.license = License.objects.create(
            organization=self.organization,
            license_type=self.license_type,
            status='active',
            billing_cycle='monthly',
            start_date=timezone.now(),
        )

        self.client.force_login(self.user)

    def test_inventory_index_requires_assigned_license(self):
        response = self.client.get(reverse('inventory:index'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/no_service_access.html')

    def test_inventory_index_allows_assigned_license(self):
        UserLicenseAssignment.objects.create(
            license=self.license,
            user_profile=self.profile,
            assigned_by=self.user,
            is_active=True,
        )

        response = self.client.get(reverse('inventory:index'))

        self.assertEqual(response.status_code, 200)


class SeedInventoryServiceCommandTests(TestCase):
    def test_seed_inventory_service_creates_service_and_license_types(self):
        call_command('seed_inventory_service')

        service = Service.objects.get(slug='inventory')
        license_type_names = set(service.license_types.values_list('name', flat=True))

        self.assertEqual(service.name, 'Inventory')
        self.assertEqual(
            license_type_names,
            {'personal_free', 'basic', 'professional', 'enterprise'},
        )


class SetupInventorySamplesCommandTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='sample-user', password='testpass123')
        self.organization = Organization.objects.create(name='Sample Org')
        self.profile = UserProfile.objects.create(
            user=self.user,
            organization=self.organization,
            is_active=True,
            is_organization_admin=True,
        )

    def test_setup_inventory_samples_creates_items_locations_reasons_and_movements(self):
        call_command('setup_inventory_samples', org_slug=self.organization.slug)

        self.assertEqual(InventoryItem.objects.filter(organization=self.organization).count(), 3)
        self.assertEqual(InventoryLocation.objects.filter(organization=self.organization).count(), 3)
        self.assertEqual(MovementReason.objects.filter(organization=self.organization).count(), 4)
        self.assertGreaterEqual(self.organization.stock_movements.count(), 4)


class InventorySignalsTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Signals Org')

    def test_creates_stock_rows_when_item_is_created(self):
        loc_a = InventoryLocation.objects.create(organization=self.organization, name='Main', code='MAIN')
        loc_b = InventoryLocation.objects.create(organization=self.organization, name='Bay', code='BAY')

        item = InventoryItem.objects.create(
            organization=self.organization,
            sku='SIGNAL-ITEM-1',
            name='Signal Item',
            unit='pcs',
        )

        self.assertTrue(ItemStock.objects.filter(item=item, location=loc_a).exists())
        self.assertTrue(ItemStock.objects.filter(item=item, location=loc_b).exists())

    def test_creates_stock_rows_when_location_is_created(self):
        item_a = InventoryItem.objects.create(
            organization=self.organization,
            sku='LOC-SIGNAL-1',
            name='Location Signal Item 1',
            unit='pcs',
        )
        item_b = InventoryItem.objects.create(
            organization=self.organization,
            sku='LOC-SIGNAL-2',
            name='Location Signal Item 2',
            unit='pcs',
        )

        location = InventoryLocation.objects.create(
            organization=self.organization,
            name='New Location',
            code='NEW-LOC',
        )

        self.assertTrue(ItemStock.objects.filter(item=item_a, location=location).exists())
        self.assertTrue(ItemStock.objects.filter(item=item_b, location=location).exists())
