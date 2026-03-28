from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Organization
from services.inventory.models import InventoryItem, InventoryLocation, MovementReason
from services.inventory.services import InventoryService


class Command(BaseCommand):
    help = "Create sample inventory data (items, locations, reasons, and stock movements)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--org-slug",
            help="Organization slug to seed. Defaults to all active organizations.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        org_slug = options.get("org_slug")

        if org_slug:
            organizations = Organization.objects.filter(slug=org_slug, is_active=True)
            if not organizations.exists():
                raise CommandError(f'No active organization found for slug "{org_slug}".')
        else:
            organizations = Organization.objects.filter(is_active=True)

        if not organizations.exists():
            self.stdout.write(self.style.WARNING("No active organizations found. Nothing to seed."))
            return

        for organization in organizations:
            self._seed_organization(organization)

        self.stdout.write(self.style.SUCCESS("Inventory sample data setup complete."))

    def _seed_organization(self, organization):
        profile = organization.members.filter(is_active=True).select_related("user").first()
        user = profile.user if profile else None

        locations = {
            "MAIN": "Main Warehouse",
            "BAY-01": "Bay 01",
            "RET": "Returns Shelf",
        }

        location_objects = {}
        for code, name in locations.items():
            location, _ = InventoryLocation.objects.get_or_create(
                organization=organization,
                code=code,
                defaults={"name": name, "is_active": True},
            )
            location_objects[code] = location

        reasons = [
            ("PURCHASE", "Purchase Inbound", "in"),
            ("SALE", "Sales Outbound", "out"),
            ("MOVE", "Internal Transfer", "transfer"),
            ("ADJ", "Stock Adjustment", "adjustment"),
        ]
        reason_objects = {}
        for code, name, movement_type in reasons:
            reason, _ = MovementReason.objects.get_or_create(
                organization=organization,
                code=code,
                defaults={
                    "name": name,
                    "movement_type": movement_type,
                    "is_active": True,
                },
            )
            reason_objects[code] = reason

        items = [
            ("WHEEL-001", "Wheel Set", "set", Decimal("4")),
            ("BOLT-100", "Bolt Pack", "pcs", Decimal("100")),
            ("FILTER-01", "Air Filter", "pcs", Decimal("8")),
        ]

        item_objects = {}
        for sku, name, unit, minimum_stock_level in items:
            item, _ = InventoryItem.objects.get_or_create(
                organization=organization,
                sku=sku,
                defaults={
                    "name": name,
                    "unit": unit,
                    "minimum_stock_level": minimum_stock_level,
                    "is_active": True,
                    "created_by": user,
                },
            )
            item_objects[sku] = item

        service = InventoryService(organization)

        wheel = item_objects["WHEEL-001"]
        bolt = item_objects["BOLT-100"]
        air_filter = item_objects["FILTER-01"]

        self._record_if_missing(
            service,
            item=wheel,
            movement_type="in",
            quantity=Decimal("20"),
            user=user,
            target_location=location_objects["MAIN"],
            reason=reason_objects["PURCHASE"],
            notes="Initial sample stock",
        )

        self._record_if_missing(
            service,
            item=bolt,
            movement_type="in",
            quantity=Decimal("500"),
            user=user,
            target_location=location_objects["MAIN"],
            reason=reason_objects["PURCHASE"],
            notes="Initial sample stock",
        )

        self._record_if_missing(
            service,
            item=air_filter,
            movement_type="in",
            quantity=Decimal("40"),
            user=user,
            target_location=location_objects["MAIN"],
            reason=reason_objects["PURCHASE"],
            notes="Initial sample stock",
        )

        self._record_if_missing(
            service,
            item=wheel,
            movement_type="transfer",
            quantity=Decimal("4"),
            user=user,
            source_location=location_objects["MAIN"],
            target_location=location_objects["BAY-01"],
            reason=reason_objects["MOVE"],
            notes="Move working stock to bay",
        )

        self.stdout.write(self.style.SUCCESS(f"Seeded inventory samples for {organization.name}."))

    def _record_if_missing(self, service, **movement_kwargs):
        item = movement_kwargs["item"]
        movement_type = movement_kwargs["movement_type"]
        quantity = movement_kwargs["quantity"]
        source_location = movement_kwargs.get("source_location")
        target_location = movement_kwargs.get("target_location")
        notes = movement_kwargs.get("notes", "")

        existing = item.movements.filter(
            movement_type=movement_type,
            quantity=quantity,
            source_location=source_location,
            target_location=target_location,
            notes=notes,
        ).exists()

        if existing:
            return

        service.record_movement(**movement_kwargs)
