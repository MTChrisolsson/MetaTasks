import csv
import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.paginator import Paginator
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from core.services.permission_service import PermissionService
from core.views import require_organization_access
from licensing.models import Service
from licensing.services import LicensingService

from .forms import (
    InventoryFieldDefinitionForm,
    InventoryItemForm,
    LocationViewSettingsForm,
    InventoryLocationForm,
    MovementReasonForm,
    StockMovementForm,
)
from .models import (
    InventoryFieldDefinition,
    InventoryFieldValue,
    InventoryItem,
    InventoryLocation,
    ItemStock,
    MovementReason,
    StockMovement,
)
from .serializers import (
    InventoryItemSerializer,
    InventoryLocationSerializer,
    ItemStockSerializer,
    StockMovementSerializer,
)
from .services import InventoryService


SERVICE_SLUG = 'inventory'

LOCATION_DEFAULT_COLUMNS = [
    ('sku', 'SKU'),
    ('name', 'Item Name'),
    ('quantity', 'Quantity'),
    ('unit', 'Unit'),
    ('minimum_stock_level', 'Minimum Stock Level'),
    ('status', 'Status'),
    ('description', 'Description'),
]
LOCATION_DEFAULT_COLUMN_MAP = {key: label for key, label in LOCATION_DEFAULT_COLUMNS}


def _get_user_profile(user):
    try:
        return user.mediap_profile
    except AttributeError as exc:
        raise DjangoPermissionDenied('User profile is missing.') from exc


def _get_inventory_service_model():
    return Service.objects.filter(slug=SERVICE_SLUG, is_active=True).first()


def _ensure_inventory_access(user, permission_codename=None, api=False):
    profile = _get_user_profile(user)
    exception_class = PermissionDenied if api else DjangoPermissionDenied

    if not LicensingService.has_service_access(profile, SERVICE_SLUG):
        raise exception_class('An assigned inventory license is required.')

    if permission_codename:
        permission_service = PermissionService(profile.organization)
        if not permission_service.has_permission(profile, permission_codename):
            raise exception_class(permission_service.get_missing_permission_message(permission_codename))

    return profile


def _enforce_inventory_page_access_or_response(request, permission_codename='inventory.view'):
    profile = getattr(request.user, 'mediap_profile', None)
    if not profile or not profile.organization:
        return redirect('core:setup_organization')

    service = _get_inventory_service_model()
    if not service:
        messages.error(request, 'Inventory service is not configured yet.')
        return redirect('dashboard:dashboard')

    if not LicensingService.has_service_access(profile, SERVICE_SLUG):
        return render(
            request,
            'core/no_service_access.html',
            {
                'service': service,
                'organization': profile.organization,
            },
        )

    permission_service = PermissionService(profile.organization)
    if permission_codename and not permission_service.has_permission(profile, permission_codename):
        messages.error(request, permission_service.get_missing_permission_message(permission_codename))
        return redirect('dashboard:dashboard')

    request.inventory_profile = profile
    request.inventory_service = service
    return None


def inventory_page_access_required(permission_codename='inventory.view'):
    def decorator(view_func):
        @login_required
        @require_organization_access
        def _wrapped(request, *args, **kwargs):
            response = _enforce_inventory_page_access_or_response(request, permission_codename)
            if response is not None:
                return response
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


@inventory_page_access_required('inventory.view')
def index(request):
    profile = request.inventory_profile
    organization = profile.organization

    items_count = InventoryItem.objects.filter(organization=organization, is_active=True).count()
    locations_count = InventoryLocation.objects.filter(organization=organization, is_active=True).count()
    movements_count = StockMovement.objects.filter(organization=organization).count()

    total_units = ItemStock.objects.filter(organization=organization).aggregate(
        total=Coalesce(Sum('quantity'), Value(0), output_field=DecimalField(max_digits=14, decimal_places=2))
    )['total']

    low_stock_items = (
        InventoryItem.objects.filter(organization=organization, is_active=True)
        .annotate(
            current_stock=Coalesce(
                Sum('stock_levels__quantity'),
                Value(0),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
        .filter(current_stock__lt=0 + Coalesce(Value(0), Value(0)))
    )

    low_stock_count = 0
    for item in (
        InventoryItem.objects.filter(organization=organization, is_active=True)
        .annotate(
            current_stock=Coalesce(
                Sum('stock_levels__quantity'),
                Value(0),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
    ):
        if item.current_stock < item.minimum_stock_level:
            low_stock_count += 1

    recent_movements = StockMovement.objects.filter(organization=organization).select_related(
        'item', 'source_location', 'target_location'
    ).order_by('-created_at')[:8]

    context = {
        'page_title': 'Inventory Dashboard',
        'profile': profile,
        'items_count': items_count,
        'locations_count': locations_count,
        'movements_count': movements_count,
        'low_stock_count': low_stock_count,
        'total_units': total_units,
        'recent_movements': recent_movements,
    }
    return render(request, 'inventory/dashboard.html', context)


@inventory_page_access_required('inventory.view')
def items_list(request):
    profile = request.inventory_profile
    search = request.GET.get('search', '').strip()

    queryset = InventoryItem.objects.filter(organization=profile.organization).order_by('name')
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(sku__icontains=search))

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'profile': profile,
        'items': page_obj,
        'search_query': search,
        'page_title': 'Inventory Items',
    }
    return render(request, 'inventory/items_list.html', context)


@inventory_page_access_required('inventory.view')
def item_detail(request, item_id):
    profile = request.inventory_profile
    item = get_object_or_404(InventoryItem, id=item_id, organization=profile.organization)

    stock_rows = item.stock_levels.select_related('location').order_by('location__name')
    current_total = stock_rows.aggregate(
        total=Coalesce(Sum('quantity'), Value(0), output_field=DecimalField(max_digits=14, decimal_places=2))
    )['total']
    recent_movements = item.movements.select_related('source_location', 'target_location').order_by('-created_at')[:15]

    context = {
        'profile': profile,
        'item': item,
        'stock_rows': stock_rows,
        'current_total': current_total,
        'recent_movements': recent_movements,
        'is_low_stock': current_total < item.minimum_stock_level,
        'page_title': f'Item {item.sku}',
    }
    return render(request, 'inventory/item_detail.html', context)


@inventory_page_access_required('inventory.create')
def item_create(request):
    profile = request.inventory_profile

    if request.method == 'POST':
        form = InventoryItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.organization = profile.organization
            item.created_by = request.user
            item.save()
            messages.success(request, f'Item "{item.name}" created successfully.')
            return redirect('inventory:item-detail', item_id=item.id)
    else:
        form = InventoryItemForm()

    return render(
        request,
        'inventory/item_form.html',
        {
            'profile': profile,
            'form': form,
            'page_title': 'Create Item',
            'form_title': 'Create Inventory Item',
            'submit_label': 'Create Item',
        },
    )


@inventory_page_access_required('inventory.manage_config')
def item_edit(request, item_id):
    profile = request.inventory_profile
    item = get_object_or_404(InventoryItem, id=item_id, organization=profile.organization)

    if request.method == 'POST':
        form = InventoryItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, f'Item "{item.name}" updated successfully.')
            return redirect('inventory:item-detail', item_id=item.id)
    else:
        form = InventoryItemForm(instance=item)

    return render(
        request,
        'inventory/item_form.html',
        {
            'profile': profile,
            'form': form,
            'item': item,
            'page_title': f'Edit {item.sku}',
            'form_title': f'Edit {item.name}',
            'submit_label': 'Save Changes',
        },
    )


@inventory_page_access_required('inventory.view')
def locations_list(request):
    profile = request.inventory_profile

    queryset = InventoryLocation.objects.filter(organization=profile.organization).order_by('name')
    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'profile': profile,
        'locations': page_obj,
        'page_title': 'Inventory Locations',
    }
    return render(request, 'inventory/locations_list.html', context)


@inventory_page_access_required('inventory.view')
def location_detail(request, location_id):
    profile = request.inventory_profile
    location = get_object_or_404(InventoryLocation, id=location_id, organization=profile.organization)

    stock_rows = list(location.stock_levels.select_related('item').order_by('item__name'))
    recent_movements = StockMovement.objects.filter(
        organization=profile.organization,
    ).filter(Q(source_location=location) | Q(target_location=location)).select_related('item').order_by('-created_at')[:15]

    view_settings = location.view_settings or {}
    selected_default_columns = view_settings.get('default_columns') or ['sku', 'name', 'quantity']
    selected_default_columns = [
        key for key in selected_default_columns if key in LOCATION_DEFAULT_COLUMN_MAP
    ]

    selected_custom_columns = view_settings.get('custom_columns') or []
    active_custom_fields = list(
        InventoryFieldDefinition.objects.filter(
            organization=profile.organization,
            is_active=True,
            key__in=selected_custom_columns,
        )
    )
    custom_field_map = {field.key: field for field in active_custom_fields}
    ordered_custom_fields = [
        custom_field_map[key]
        for key in selected_custom_columns
        if key in custom_field_map
    ]

    item_ids = [stock.item_id for stock in stock_rows]
    custom_values = InventoryFieldValue.objects.filter(
        organization=profile.organization,
        item_id__in=item_ids,
        definition__key__in=[field.key for field in ordered_custom_fields],
    ).select_related('definition')
    custom_values_map = {
        (field_value.item_id, field_value.definition.key): field_value.value
        for field_value in custom_values
    }

    table_headers = [LOCATION_DEFAULT_COLUMN_MAP[col] for col in selected_default_columns]
    table_headers.extend([field.name for field in ordered_custom_fields])

    table_rows = []
    for stock in stock_rows:
        default_data = {
            'sku': stock.item.sku,
            'name': stock.item.name,
            'quantity': stock.quantity,
            'unit': stock.item.unit,
            'minimum_stock_level': stock.item.minimum_stock_level,
            'status': 'Low' if stock.quantity < stock.item.minimum_stock_level else 'OK',
            'description': stock.item.description or '-',
        }

        custom_data = {}
        for field in ordered_custom_fields:
            raw_value = custom_values_map.get((stock.item_id, field.key), '-')
            if isinstance(raw_value, (dict, list)):
                custom_data[field.key] = json.dumps(raw_value, ensure_ascii=True)
            elif raw_value in (None, ''):
                custom_data[field.key] = '-'
            else:
                custom_data[field.key] = str(raw_value)

        row_values = [default_data[col] for col in selected_default_columns]
        row_values.extend(custom_data[field.key] for field in ordered_custom_fields)
        table_rows.append({'values': row_values})

    context = {
        'profile': profile,
        'location': location,
        'stock_rows': table_rows,
        'stock_headers': table_headers,
        'recent_movements': recent_movements,
        'page_title': f'Location {location.code}',
    }
    return render(request, 'inventory/location_detail.html', context)


@inventory_page_access_required('inventory.manage_config')
def location_view_settings(request, location_id):
    profile = request.inventory_profile
    location = get_object_or_404(InventoryLocation, id=location_id, organization=profile.organization)

    custom_fields = list(
        InventoryFieldDefinition.objects.filter(
            organization=profile.organization,
            is_active=True,
        ).order_by('name')
    )

    initial_settings = location.view_settings or {}
    initial = {
        'default_columns': initial_settings.get('default_columns') or ['sku', 'name', 'quantity'],
        'custom_columns': initial_settings.get('custom_columns') or [],
    }

    if request.method == 'POST':
        form = LocationViewSettingsForm(
            request.POST,
            custom_field_definitions=custom_fields,
        )
        if form.is_valid():
            location.view_settings = {
                'default_columns': form.cleaned_data['default_columns'],
                'custom_columns': form.cleaned_data['custom_columns'],
            }
            location.save(update_fields=['view_settings', 'updated_at'])
            messages.success(request, f'Updated visible fields for location "{location.name}".')
            return redirect('inventory:location-detail', location_id=location.id)
    else:
        form = LocationViewSettingsForm(
            initial=initial,
            custom_field_definitions=custom_fields,
        )

    return render(
        request,
        'inventory/location_view_settings.html',
        {
            'profile': profile,
            'location': location,
            'form': form,
            'custom_field_count': len(custom_fields),
            'page_title': f'Visible Fields: {location.code}',
        },
    )


@inventory_page_access_required('inventory.create')
def location_create(request):
    profile = request.inventory_profile

    if request.method == 'POST':
        form = InventoryLocationForm(request.POST)
        if form.is_valid():
            location = form.save(commit=False)
            location.organization = profile.organization
            location.save()
            messages.success(request, f'Location "{location.name}" created successfully.')
            return redirect('inventory:location-detail', location_id=location.id)
    else:
        form = InventoryLocationForm()

    return render(
        request,
        'inventory/location_form.html',
        {
            'profile': profile,
            'form': form,
            'page_title': 'Create Location',
            'form_title': 'Create Inventory Location',
            'submit_label': 'Create Location',
        },
    )


@inventory_page_access_required('inventory.manage_config')
def location_edit(request, location_id):
    profile = request.inventory_profile
    location = get_object_or_404(InventoryLocation, id=location_id, organization=profile.organization)

    if request.method == 'POST':
        form = InventoryLocationForm(request.POST, instance=location)
        if form.is_valid():
            form.save()
            messages.success(request, f'Location "{location.name}" updated successfully.')
            return redirect('inventory:location-detail', location_id=location.id)
    else:
        form = InventoryLocationForm(instance=location)

    return render(
        request,
        'inventory/location_form.html',
        {
            'profile': profile,
            'form': form,
            'location': location,
            'page_title': f'Edit {location.code}',
            'form_title': f'Edit {location.name}',
            'submit_label': 'Save Changes',
        },
    )


@inventory_page_access_required('inventory.view')
def movements_list(request):
    profile = request.inventory_profile
    movement_type = request.GET.get('movement_type', '').strip()

    queryset = StockMovement.objects.filter(organization=profile.organization).select_related(
        'item', 'source_location', 'target_location', 'reason'
    )
    if movement_type:
        queryset = queryset.filter(movement_type=movement_type)

    queryset = queryset.order_by('-created_at')
    paginator = Paginator(queryset, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'profile': profile,
        'movements': page_obj,
        'movement_type': movement_type,
        'movement_types': StockMovement._meta.get_field('movement_type').choices,
        'page_title': 'Stock Movements',
    }
    return render(request, 'inventory/movements_list.html', context)


@inventory_page_access_required('inventory.adjust')
def movement_create(request):
    profile = request.inventory_profile

    if request.method == 'POST':
        form = StockMovementForm(request.POST, organization=profile.organization)
        if form.is_valid():
            inventory_service = InventoryService(profile.organization)
            movement = inventory_service.record_movement(
                item=form.cleaned_data['item'],
                movement_type=form.cleaned_data['movement_type'],
                quantity=form.cleaned_data['quantity'],
                user=request.user,
                source_location=form.cleaned_data.get('source_location'),
                target_location=form.cleaned_data.get('target_location'),
                reason=form.cleaned_data.get('reason'),
                notes=form.cleaned_data.get('notes', ''),
            )
            messages.success(request, f'Movement recorded for {movement.item.sku}.')
            return redirect('inventory:movements-list')
    else:
        form = StockMovementForm(organization=profile.organization)

    return render(
        request,
        'inventory/movement_form.html',
        {
            'profile': profile,
            'form': form,
            'page_title': 'Record Movement',
        },
    )


@inventory_page_access_required('inventory.view')
def low_stock_alerts(request):
    profile = request.inventory_profile

    items = (
        InventoryItem.objects.filter(organization=profile.organization, is_active=True)
        .annotate(
            current_stock=Coalesce(
                Sum('stock_levels__quantity'),
                Value(0),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
        .order_by('name')
    )

    alert_items = [item for item in items if item.current_stock < item.minimum_stock_level]

    context = {
        'profile': profile,
        'items': alert_items,
        'page_title': 'Low Stock Alerts',
    }
    return render(request, 'inventory/low_stock_alerts.html', context)


@inventory_page_access_required('inventory.manage_config')
def configuration(request):
    profile = request.inventory_profile

    reasons = MovementReason.objects.filter(organization=profile.organization).order_by('name')
    field_definitions = InventoryFieldDefinition.objects.filter(organization=profile.organization).order_by('name')

    context = {
        'profile': profile,
        'reasons': reasons,
        'field_definitions': field_definitions,
        'page_title': 'Inventory Configuration',
    }
    return render(request, 'inventory/configuration.html', context)


@inventory_page_access_required('inventory.manage_config')
def movement_reason_create(request):
    profile = request.inventory_profile

    if request.method == 'POST':
        form = MovementReasonForm(request.POST)
        if form.is_valid():
            reason = form.save(commit=False)
            reason.organization = profile.organization
            reason.save()
            messages.success(request, f'Movement reason "{reason.name}" created.')
            return redirect('inventory:configuration')
    else:
        form = MovementReasonForm()

    return render(
        request,
        'inventory/movement_reason_form.html',
        {
            'profile': profile,
            'form': form,
            'page_title': 'Create Movement Reason',
            'form_title': 'Create Movement Reason',
            'submit_label': 'Create Reason',
        },
    )


@inventory_page_access_required('inventory.manage_config')
def movement_reason_edit(request, reason_id):
    profile = request.inventory_profile
    reason = get_object_or_404(MovementReason, id=reason_id, organization=profile.organization)

    if request.method == 'POST':
        form = MovementReasonForm(request.POST, instance=reason)
        if form.is_valid():
            form.save()
            messages.success(request, f'Movement reason "{reason.name}" updated.')
            return redirect('inventory:configuration')
    else:
        form = MovementReasonForm(instance=reason)

    return render(
        request,
        'inventory/movement_reason_form.html',
        {
            'profile': profile,
            'form': form,
            'reason': reason,
            'page_title': f'Edit {reason.name}',
            'form_title': f'Edit {reason.name}',
            'submit_label': 'Save Changes',
        },
    )


@inventory_page_access_required('inventory.manage_config')
def field_definition_create(request):
    profile = request.inventory_profile

    if request.method == 'POST':
        form = InventoryFieldDefinitionForm(request.POST)
        if form.is_valid():
            field_definition = form.save(commit=False)
            field_definition.organization = profile.organization
            field_definition.save()
            messages.success(request, f'Field definition "{field_definition.name}" created.')
            return redirect('inventory:configuration')
    else:
        form = InventoryFieldDefinitionForm()

    return render(
        request,
        'inventory/field_definition_form.html',
        {
            'profile': profile,
            'form': form,
            'page_title': 'Create Custom Field',
            'form_title': 'Create Custom Field',
            'submit_label': 'Create Field',
        },
    )


@inventory_page_access_required('inventory.manage_config')
def field_definition_edit(request, field_id):
    profile = request.inventory_profile
    field_definition = get_object_or_404(
        InventoryFieldDefinition,
        id=field_id,
        organization=profile.organization,
    )

    if request.method == 'POST':
        form = InventoryFieldDefinitionForm(request.POST, instance=field_definition)
        if form.is_valid():
            form.save()
            messages.success(request, f'Field definition "{field_definition.name}" updated.')
            return redirect('inventory:configuration')
    else:
        form = InventoryFieldDefinitionForm(instance=field_definition)

    return render(
        request,
        'inventory/field_definition_form.html',
        {
            'profile': profile,
            'form': form,
            'field_definition': field_definition,
            'page_title': f'Edit {field_definition.name}',
            'form_title': f'Edit {field_definition.name}',
            'submit_label': 'Save Changes',
        },
    )


@inventory_page_access_required('inventory.export')
def export_stock_csv(request):
    profile = request.inventory_profile
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="inventory_stock.csv"'

    writer = csv.writer(response)
    writer.writerow(['SKU', 'Item Name', 'Location', 'Quantity', 'Updated At'])

    rows = ItemStock.objects.filter(organization=profile.organization).select_related('item', 'location').order_by(
        'item__sku',
        'location__code',
    )

    for row in rows:
        writer.writerow([
            row.item.sku,
            row.item.name,
            row.location.code,
            row.quantity,
            row.updated_at.isoformat() if row.updated_at else '',
        ])

    return response


@inventory_page_access_required('inventory.export')
def export_movements_csv(request):
    profile = request.inventory_profile
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="inventory_movements.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Timestamp',
        'SKU',
        'Item Name',
        'Type',
        'Quantity',
        'Source',
        'Target',
        'Reason',
        'Notes',
    ])

    rows = StockMovement.objects.filter(organization=profile.organization).select_related(
        'item',
        'source_location',
        'target_location',
        'reason',
    ).order_by('-created_at')

    for row in rows:
        writer.writerow([
            row.created_at.isoformat() if row.created_at else '',
            row.item.sku,
            row.item.name,
            row.movement_type,
            row.quantity,
            row.source_location.code if row.source_location else '',
            row.target_location.code if row.target_location else '',
            row.reason.name if row.reason else '',
            row.notes,
        ])

    return response


class InventoryScopedViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    action_permission_map = {
        'list': 'inventory.view',
        'retrieve': 'inventory.view',
    }

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.inventory_profile = _ensure_inventory_access(
            request.user,
            self.get_required_permission(),
            api=True,
        )

    def get_required_permission(self):
        return self.action_permission_map.get(self.action, 'inventory.view')

    def get_queryset(self):
        organization = self.inventory_profile.organization
        return self.queryset.filter(organization=organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.inventory_profile.organization)


class InventoryItemViewSet(InventoryScopedViewSet):
    queryset = InventoryItem.objects.select_related('organization').all()
    serializer_class = InventoryItemSerializer
    action_permission_map = {
        'list': 'inventory.view',
        'retrieve': 'inventory.view',
        'create': 'inventory.create',
        'update': 'inventory.manage_config',
        'partial_update': 'inventory.manage_config',
        'destroy': 'inventory.manage_config',
    }


class InventoryLocationViewSet(InventoryScopedViewSet):
    queryset = InventoryLocation.objects.select_related('organization').all()
    serializer_class = InventoryLocationSerializer
    action_permission_map = {
        'list': 'inventory.view',
        'retrieve': 'inventory.view',
        'create': 'inventory.create',
        'update': 'inventory.manage_config',
        'partial_update': 'inventory.manage_config',
        'destroy': 'inventory.manage_config',
    }


class ItemStockViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = ItemStock.objects.select_related('organization', 'item', 'location').all()
    serializer_class = ItemStockSerializer
    action_permission_map = {
        'list': 'inventory.view',
        'retrieve': 'inventory.view',
    }

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.inventory_profile = _ensure_inventory_access(
            request.user,
            self.action_permission_map.get(self.action, 'inventory.view'),
            api=True,
        )

    def get_queryset(self):
        return self.queryset.filter(organization=self.inventory_profile.organization)


class StockMovementViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = StockMovement.objects.select_related('organization', 'item').all()
    serializer_class = StockMovementSerializer

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.inventory_profile = _ensure_inventory_access(
            request.user,
            self.get_required_permission(),
            api=True,
        )

    def get_required_permission(self):
        if self.action == 'create':
            movement_type = self.request.data.get('movement_type')
            if movement_type == 'transfer':
                return 'inventory.transfer'
            return 'inventory.adjust'
        return 'inventory.view'

    def get_queryset(self):
        return self.queryset.filter(organization=self.inventory_profile.organization)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = InventoryService(self.inventory_profile.organization)
        movement = service.record_movement(
            item=serializer.validated_data['item'],
            movement_type=serializer.validated_data['movement_type'],
            quantity=serializer.validated_data['quantity'],
            user=request.user,
            source_location=serializer.validated_data.get('source_location'),
            target_location=serializer.validated_data.get('target_location'),
            reason=serializer.validated_data.get('reason'),
            notes=serializer.validated_data.get('notes', ''),
            metadata=serializer.validated_data.get('metadata') or {},
        )

        output = self.get_serializer(movement)
        return Response(output.data, status=status.HTTP_201_CREATED)
