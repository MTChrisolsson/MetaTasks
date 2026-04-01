from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from core.models import Organization


class InventoryLocation(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='inventory_locations',
    )
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=32)
    description = models.TextField(blank=True)
    view_settings = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('organization', 'code')]
        indexes = [
            models.Index(fields=['organization', 'is_active']),
        ]
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"


class InventoryItem(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='inventory_items',
    )
    sku = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=20, default='pcs')
    minimum_stock_level = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    custom_data = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_items_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('organization', 'sku')]
        indexes = [
            models.Index(fields=['organization', 'sku']),
            models.Index(fields=['organization', 'is_active']),
        ]
        ordering = ['name']

    def __str__(self):
        return f"{self.sku} - {self.name}"


class ItemStock(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='item_stocks',
    )
    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.CASCADE,
        related_name='stock_levels',
    )
    location = models.ForeignKey(
        InventoryLocation,
        on_delete=models.CASCADE,
        related_name='stock_levels',
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('item', 'location')]
        indexes = [
            models.Index(fields=['organization', 'item']),
            models.Index(fields=['organization', 'location']),
        ]

    def __str__(self):
        return f"{self.item.sku} @ {self.location.code}: {self.quantity}"


class MovementReason(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='inventory_movement_reasons',
    )
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    movement_type = models.CharField(
        max_length=16,
        choices=[
            ('in', 'In'),
            ('out', 'Out'),
            ('transfer', 'Transfer'),
            ('adjustment', 'Adjustment'),
        ],
        default='adjustment',
    )
    requires_approval = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [('organization', 'code')]
        indexes = [models.Index(fields=['organization', 'movement_type'])]
        ordering = ['name']

    def __str__(self):
        return self.name


class StockMovement(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='stock_movements',
    )
    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.CASCADE,
        related_name='movements',
    )
    movement_type = models.CharField(
        max_length=16,
        choices=[
            ('in', 'In'),
            ('out', 'Out'),
            ('transfer', 'Transfer'),
            ('adjustment', 'Adjustment'),
        ],
    )
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
    )
    source_location = models.ForeignKey(
        InventoryLocation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='outbound_movements',
    )
    target_location = models.ForeignKey(
        InventoryLocation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inbound_movements',
    )
    reason = models.ForeignKey(
        MovementReason,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='movements',
    )
    notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_movements_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['organization', 'created_at']),
            models.Index(fields=['organization', 'movement_type']),
            models.Index(fields=['item', 'created_at']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.item.sku}: {self.movement_type} {self.quantity}"


class InventoryFieldDefinition(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='inventory_field_definitions',
    )
    location = models.ForeignKey(
        InventoryLocation,
        on_delete=models.CASCADE,
        related_name='custom_field_definitions',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100)
    key = models.SlugField(max_length=100)
    field_type = models.CharField(
        max_length=30,
        choices=[
            ('text', 'Text'),
            ('number', 'Number'),
            ('bool', 'Boolean'),
            ('date', 'Date'),
            ('select', 'Select'),
        ],
        default='text',
    )
    config = models.JSONField(default=dict, blank=True)
    is_required = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [('organization', 'key')]
        ordering = ['name']

    def __str__(self):
        if self.location_id:
            return f"{self.name} ({self.location.code})"
        return self.name


class InventoryFieldValue(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='inventory_field_values',
    )
    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.CASCADE,
        related_name='custom_field_values',
    )
    definition = models.ForeignKey(
        InventoryFieldDefinition,
        on_delete=models.CASCADE,
        related_name='values',
    )
    value = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [('item', 'definition')]

    def __str__(self):
        return f"{self.item.sku} / {self.definition.key}"
