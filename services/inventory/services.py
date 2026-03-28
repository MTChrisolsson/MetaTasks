from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import AuditLog, Notification, UserProfile
from .models import ItemStock, StockMovement


class InventoryService:
    """Core inventory business logic for organization-scoped stock operations."""

    def __init__(self, organization):
        self.organization = organization

    def get_or_create_stock(self, item, location):
        self._validate_item_belongs_to_org(item)
        self._validate_location_belongs_to_org(location)
        stock, _ = ItemStock.objects.get_or_create(
            organization=self.organization,
            item=item,
            location=location,
            defaults={'quantity': Decimal('0')},
        )
        return stock

    def _validate_item_belongs_to_org(self, item):
        if item.organization_id != self.organization.id:
            raise ValidationError('The selected item does not belong to this organization.')

    def _validate_location_belongs_to_org(self, location):
        if location and location.organization_id != self.organization.id:
            raise ValidationError('The selected location does not belong to this organization.')

    def _validate_reason_belongs_to_org(self, reason):
        if reason and reason.organization_id != self.organization.id:
            raise ValidationError('The selected movement reason does not belong to this organization.')

    def _notify_low_stock(self, item):
        total_quantity = sum(stock.quantity for stock in item.stock_levels.all())
        if total_quantity >= item.minimum_stock_level:
            return

        title = f'Low stock alert: {item.name}'
        message = (
            f'{item.name} ({item.sku}) is below minimum level. '
            f'Current stock: {total_quantity}. Minimum: {item.minimum_stock_level}.'
        )

        admin_profiles = UserProfile.objects.filter(
            organization=self.organization,
            is_active=True,
            is_organization_admin=True,
            user__is_active=True,
        ).select_related('user')

        for profile in admin_profiles:
            recent_existing = Notification.objects.filter(
                recipient=profile.user,
                title=title,
                content_type='InventoryItem',
                object_id=str(item.id),
                is_read=False,
            ).exists()
            if recent_existing:
                continue

            notification = Notification.objects.create(
                recipient=profile.user,
                title=title,
                message=message,
                notification_type='warning',
                content_type='InventoryItem',
                object_id=str(item.id),
                action_url=f'/services/inventory/items/{item.id}/',
                action_text='View Item',
            )

            try:
                from core.notification_views import send_notification_email

                send_notification_email(notification)
            except Exception:
                # Email delivery must not break stock movements.
                pass

    def _create_audit_log(self, movement, user):
        AuditLog.objects.create(
            user=user,
            action='create',
            content_type='StockMovement',
            object_id=str(movement.id),
            object_repr=str(movement),
            additional_data={
                'organization_id': str(self.organization.id),
                'item_id': movement.item_id,
                'movement_type': movement.movement_type,
                'quantity': str(movement.quantity),
                'source_location_id': movement.source_location_id,
                'target_location_id': movement.target_location_id,
                'timestamp': timezone.now().isoformat(),
            },
        )

    @transaction.atomic
    def record_movement(
        self,
        *,
        item,
        movement_type,
        quantity,
        user=None,
        source_location=None,
        target_location=None,
        reason=None,
        notes='',
        metadata=None,
    ):
        quantity = Decimal(quantity)
        if quantity <= 0:
            raise ValidationError('Quantity must be greater than zero.')

        self._validate_item_belongs_to_org(item)
        self._validate_location_belongs_to_org(source_location)
        self._validate_location_belongs_to_org(target_location)
        self._validate_reason_belongs_to_org(reason)

        if movement_type in {'out', 'transfer'} and not source_location:
            raise ValidationError('Source location is required for outbound and transfer movements.')
        if movement_type in {'in', 'transfer'} and not target_location:
            raise ValidationError('Target location is required for inbound and transfer movements.')

        if movement_type in {'out', 'transfer'}:
            source_stock = self.get_or_create_stock(item, source_location)
            if source_stock.quantity < quantity:
                raise ValidationError('Insufficient stock at source location.')
            source_stock.quantity -= quantity
            source_stock.save(update_fields=['quantity', 'updated_at'])

        if movement_type in {'in', 'transfer'}:
            target_stock = self.get_or_create_stock(item, target_location)
            target_stock.quantity += quantity
            target_stock.save(update_fields=['quantity', 'updated_at'])

        if movement_type == 'adjustment':
            if not target_location:
                raise ValidationError('Target location is required for adjustment movements.')
            adjustment_stock = self.get_or_create_stock(item, target_location)
            adjustment_stock.quantity += quantity
            adjustment_stock.save(update_fields=['quantity', 'updated_at'])

        movement = StockMovement.objects.create(
            organization=self.organization,
            item=item,
            movement_type=movement_type,
            quantity=quantity,
            source_location=source_location,
            target_location=target_location,
            reason=reason,
            notes=notes,
            metadata=metadata or {},
            created_by=user,
        )

        self._create_audit_log(movement, user)
        self._notify_low_stock(item)
        return movement
