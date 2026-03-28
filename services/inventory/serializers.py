from rest_framework import serializers

from .models import InventoryItem, InventoryLocation, ItemStock, StockMovement


class InventoryLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryLocation
        fields = ['id', 'name', 'code', 'description', 'is_active']


class InventoryItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryItem
        fields = [
            'id',
            'sku',
            'name',
            'description',
            'unit',
            'minimum_stock_level',
            'custom_data',
            'is_active',
        ]


class ItemStockSerializer(serializers.ModelSerializer):
    item = InventoryItemSerializer(read_only=True)
    location = InventoryLocationSerializer(read_only=True)

    class Meta:
        model = ItemStock
        fields = ['id', 'item', 'location', 'quantity', 'updated_at']


class StockMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockMovement
        fields = [
            'id',
            'item',
            'movement_type',
            'quantity',
            'source_location',
            'target_location',
            'reason',
            'notes',
            'metadata',
            'created_at',
        ]
