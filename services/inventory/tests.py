from decimal import Decimal

from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Organization, UserProfile
from licensing.models import License, LicenseType, Service, UserLicenseAssignment
from .models import (
    InventoryFieldDefinition,
    InventoryFieldValue,
    InventoryItem,
    InventoryLocation,
    ItemStock,
    MovementReason,
)
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


class InventoryLocationCustomFieldTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='custom-field-user', password='testpass123')
        self.organization = Organization.objects.create(name='Custom Field Org')
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
        UserLicenseAssignment.objects.create(
            license=self.license,
            user_profile=self.profile,
            assigned_by=self.user,
            is_active=True,
        )

        self.location = InventoryLocation.objects.create(
            organization=self.organization,
            name='Main Warehouse',
            code='MAIN',
        )
        self.other_location = InventoryLocation.objects.create(
            organization=self.organization,
            name='Vehicle Bay',
            code='BAY',
        )
        self.client.force_login(self.user)

    def test_item_create_shows_only_selected_location_custom_fields(self):
        InventoryFieldDefinition.objects.create(
            organization=self.organization,
            location=self.location,
            name='Batch Number',
            key='batch_number_main',
            field_type='text',
        )
        InventoryFieldDefinition.objects.create(
            organization=self.organization,
            location=self.other_location,
            name='Bay Marker',
            key='bay_marker',
            field_type='text',
        )

        response = self.client.get(reverse('inventory:item-create'), {'location': self.location.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Batch Number')
        self.assertNotContains(response, 'Bay Marker')

    def test_item_create_saves_location_specific_custom_field_value(self):
        field_definition = InventoryFieldDefinition.objects.create(
            organization=self.organization,
            location=self.location,
            name='Batch Number',
            key='batch_number_main',
            field_type='text',
        )

        response = self.client.post(
            reverse('inventory:item-create'),
            {
                'location': self.location.id,
                'sku': 'LOC-ITEM-1',
                'name': 'Warehouse Wheel Set',
                'description': 'Stored in main warehouse',
                'unit': 'set',
                'minimum_stock_level': '2',
                'is_active': 'on',
                f'custom_{field_definition.id}': 'BN-2026-001',
            },
        )

        item = InventoryItem.objects.get(organization=self.organization, sku='LOC-ITEM-1')

        self.assertRedirects(response, reverse('inventory:item-detail', kwargs={'item_id': item.id}))
        self.assertEqual(
            InventoryFieldValue.objects.get(item=item, definition=field_definition).value,
            'BN-2026-001',
        )

    def test_location_detail_displays_location_specific_custom_field_value(self):
        field_definition = InventoryFieldDefinition.objects.create(
            organization=self.organization,
            location=self.location,
            name='Batch Number',
            key='batch_number_main',
            field_type='text',
        )
        item = InventoryItem.objects.create(
            organization=self.organization,
            sku='LOC-DISPLAY-1',
            name='Display Item',
            unit='pcs',
        )
        InventoryFieldValue.objects.create(
            organization=self.organization,
            item=item,
            definition=field_definition,
            value='BN-2026-777',
        )
        self.location.view_settings = {
            'default_columns': ['sku', 'name'],
            'custom_columns': [field_definition.key],
        }
        self.location.save(update_fields=['view_settings'])

        response = self.client.get(reverse('inventory:location-detail', kwargs={'location_id': self.location.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Batch Number')
        self.assertContains(response, 'BN-2026-777')

    def test_location_detail_allows_all_default_columns_to_be_hidden(self):
        self.location.view_settings = {
            'default_columns': [],
            'custom_columns': [],
        }
        self.location.save(update_fields=['view_settings'])

        response = self.client.get(reverse('inventory:location-detail', kwargs={'location_id': self.location.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No columns are currently enabled for this location.')
        self.assertEqual(response.context['stock_headers'], [])

    def test_location_custom_field_order_is_used_on_item_create_form(self):
        first_field = InventoryFieldDefinition.objects.create(
            organization=self.organization,
            location=self.location,
            name='First Field',
            key='first_field',
            field_type='text',
        )
        second_field = InventoryFieldDefinition.objects.create(
            organization=self.organization,
            location=self.location,
            name='Second Field',
            key='second_field',
            field_type='text',
        )
        self.location.view_settings = {
            'default_columns': [],
            'custom_columns': [second_field.key, first_field.key],
        }
        self.location.save(update_fields=['view_settings'])

        response = self.client.get(reverse('inventory:item-create'), {'location': self.location.id})

        self.assertEqual(response.status_code, 200)
        custom_labels = [field.label for field in response.context['custom_fields']]
        self.assertEqual(custom_labels[:2], ['Second Field', 'First Field'])

    def test_disabled_default_fields_are_hidden_on_item_create_form(self):
        self.location.view_settings = {
            'default_columns': ['name'],
            'custom_columns': [],
        }
        self.location.save(update_fields=['view_settings'])

        response = self.client.get(reverse('inventory:item-create'), {'location': self.location.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Name')
        self.assertNotContains(response, 'SKU')
        self.assertNotContains(response, 'Unit')
        self.assertNotContains(response, 'Description')
        self.assertNotContains(response, 'Minimum stock level')

    def test_item_create_can_submit_when_hidden_required_defaults_disabled(self):
        custom_field = InventoryFieldDefinition.objects.create(
            organization=self.organization,
            location=self.location,
            name='Only Visible Custom',
            key='only_visible_custom',
            field_type='text',
            is_required=True,
        )
        self.location.view_settings = {
            'default_columns': [],
            'custom_columns': [custom_field.key],
        }
        self.location.save(update_fields=['view_settings'])

        response = self.client.post(
            reverse('inventory:item-create'),
            {
                'location': self.location.id,
                'is_active': 'on',
                f'custom_{custom_field.id}': 'Visible Value',
            },
        )

        item = InventoryItem.objects.get(organization=self.organization, name='Visible Value')
        self.assertRedirects(response, reverse('inventory:item-detail', kwargs={'item_id': item.id}))
        self.assertTrue(item.sku.startswith(self.location.code))


class InventoryLocationsListFilterTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='location-filter-user', password='testpass123')
        self.organization = Organization.objects.create(name='Location Filter Org')
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
        UserLicenseAssignment.objects.create(
            license=self.license,
            user_profile=self.profile,
            assigned_by=self.user,
            is_active=True,
        )

        InventoryLocation.objects.create(
            organization=self.organization,
            name='Main Warehouse',
            code='MAIN',
            description='Primary storage',
            is_active=True,
        )
        InventoryLocation.objects.create(
            organization=self.organization,
            name='Backup Bay',
            code='BAY',
            description='Secondary storage area',
            is_active=False,
        )

        self.client.force_login(self.user)

    def test_locations_list_search_filters_by_name_code_and_description(self):
        response = self.client.get(reverse('inventory:locations-list'), {'search': 'main'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Main Warehouse')
        self.assertNotContains(response, 'Backup Bay')

    def test_locations_list_status_filter_active(self):
        response = self.client.get(reverse('inventory:locations-list'), {'status': 'active'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Main Warehouse')
        self.assertNotContains(response, 'Backup Bay')

    def test_locations_list_status_filter_inactive(self):
        response = self.client.get(reverse('inventory:locations-list'), {'status': 'inactive'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Backup Bay')
        self.assertNotContains(response, 'Main Warehouse')
