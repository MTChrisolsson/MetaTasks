from decimal import Decimal

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import InventoryItem, InventoryLocation, ItemStock


@receiver(post_save, sender=InventoryItem)
def create_item_stock_rows_for_existing_locations(sender, instance, created, **kwargs):
    """Initialize stock records for all active locations when an item is created."""
    if not created:
        return

    locations = InventoryLocation.objects.filter(organization=instance.organization, is_active=True).only("id")
    stock_rows = [
        ItemStock(
            organization=instance.organization,
            item=instance,
            location=location,
            quantity=Decimal("0"),
        )
        for location in locations
    ]
    if stock_rows:
        ItemStock.objects.bulk_create(stock_rows, ignore_conflicts=True)


@receiver(post_save, sender=InventoryLocation)
def create_location_stock_rows_for_existing_items(sender, instance, created, **kwargs):
    """Initialize stock records for all active items when a location is created."""
    if not created:
        return

    items = InventoryItem.objects.filter(organization=instance.organization, is_active=True).only("id")
    stock_rows = [
        ItemStock(
            organization=instance.organization,
            item=item,
            location=instance,
            quantity=Decimal("0"),
        )
        for item in items
    ]
    if stock_rows:
        ItemStock.objects.bulk_create(stock_rows, ignore_conflicts=True)
