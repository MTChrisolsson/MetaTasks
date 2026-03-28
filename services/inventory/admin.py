from django.contrib import admin

from .models import (
    InventoryFieldDefinition,
    InventoryFieldValue,
    InventoryItem,
    InventoryLocation,
    ItemStock,
    MovementReason,
    StockMovement,
)


@admin.register(InventoryLocation)
class InventoryLocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'organization', 'is_active')
    list_filter = ('organization', 'is_active')
    search_fields = ('name', 'code')


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ('sku', 'name', 'organization', 'unit', 'minimum_stock_level', 'is_active')
    list_filter = ('organization', 'is_active', 'unit')
    search_fields = ('sku', 'name')


@admin.register(ItemStock)
class ItemStockAdmin(admin.ModelAdmin):
    list_display = ('item', 'location', 'organization', 'quantity', 'updated_at')
    list_filter = ('organization', 'location')
    search_fields = ('item__sku', 'item__name', 'location__name')


@admin.register(MovementReason)
class MovementReasonAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'organization', 'movement_type', 'requires_approval', 'is_active')
    list_filter = ('organization', 'movement_type', 'requires_approval', 'is_active')
    search_fields = ('name', 'code')


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('item', 'movement_type', 'quantity', 'organization', 'created_at')
    list_filter = ('organization', 'movement_type', 'created_at')
    search_fields = ('item__sku', 'item__name', 'notes')


@admin.register(InventoryFieldDefinition)
class InventoryFieldDefinitionAdmin(admin.ModelAdmin):
    list_display = ('name', 'key', 'organization', 'field_type', 'is_required', 'is_active')
    list_filter = ('organization', 'field_type', 'is_required', 'is_active')
    search_fields = ('name', 'key')


@admin.register(InventoryFieldValue)
class InventoryFieldValueAdmin(admin.ModelAdmin):
    list_display = ('item', 'definition', 'organization')
    list_filter = ('organization',)
    search_fields = ('item__sku', 'definition__key')
