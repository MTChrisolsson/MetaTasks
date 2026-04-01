from decimal import Decimal

from django import forms
from django.db.models import Q

from .models import (
    InventoryFieldDefinition,
    InventoryFieldValue,
    InventoryItem,
    InventoryLocation,
    MovementReason,
    StockMovement,
)


class InventoryItemForm(forms.ModelForm):
    location = forms.ModelChoiceField(
        queryset=InventoryLocation.objects.none(),
        required=False,
        empty_label='Select location to load custom fields',
        help_text='Pick a location to load any fields configured specifically for that location.',
    )

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.custom_field_names = []
        self.standard_field_names = []
        self.selected_location = None
        self._show_sku = True
        self._show_name = True

        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'h-4 w-4 rounded border-gray-300 text-amber-600 focus:ring-amber-500')
            else:
                field.widget.attrs.setdefault(
                    'class',
                    'block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200',
                )

        self.fields['sku'].widget.attrs.setdefault('placeholder', 'WHEEL-001')
        self.fields['name'].widget.attrs.setdefault('placeholder', 'Wheel Set')
        self.fields['description'].widget.attrs.setdefault('rows', 4)
        self.fields['description'].widget.attrs.setdefault('placeholder', 'Optional notes for this item')
        self.fields['unit'].widget.attrs.setdefault('placeholder', 'pcs / set / kg')
        self.fields['minimum_stock_level'].widget.attrs.setdefault('placeholder', '0')
        self.fields['minimum_stock_level'].help_text = 'An alert appears when current stock goes below this number.'

        if organization:
            self.fields['location'].queryset = InventoryLocation.objects.filter(
                organization=organization,
                is_active=True,
            ).order_by('name')

        selected_location_id = None
        if self.is_bound:
            selected_location_id = self.data.get(self.add_prefix('location')) or self.data.get('location')
        else:
            selected_location_id = self.initial.get('location')

        if selected_location_id:
            try:
                self.selected_location = self.fields['location'].queryset.get(pk=selected_location_id)
            except (InventoryLocation.DoesNotExist, ValueError, TypeError):
                self.selected_location = None

        if self.selected_location:
            self.fields['location'].initial = self.selected_location

        self._apply_location_default_field_settings()
        self._add_custom_fields()
        self.order_fields(['location', *self.standard_field_names, *self.custom_field_names, 'is_active'])

    class Meta:
        model = InventoryItem
        fields = [
            'sku',
            'name',
            'description',
            'unit',
            'minimum_stock_level',
            'is_active',
        ]

    def _add_custom_fields(self):
        if not self.organization:
            return

        field_definitions = InventoryFieldDefinition.objects.filter(
            organization=self.organization,
            is_active=True,
        )
        if self.selected_location:
            field_definitions = field_definitions.filter(
                    Q(location__isnull=True) | Q(location=self.selected_location)
            )
        else:
            field_definitions = field_definitions.filter(location__isnull=True)

        field_definitions = list(field_definitions.select_related('location').order_by('location__name', 'name'))
        if self.selected_location:
            configured_order = (self.selected_location.view_settings or {}).get('custom_columns') or []
            definition_map = {definition.key: definition for definition in field_definitions}
            ordered_definitions = [
                definition_map[key]
                for key in configured_order
                if key in definition_map
            ]
            remaining_definitions = [
                definition for definition in field_definitions
                if definition.key not in set(configured_order)
            ]
            field_definitions = ordered_definitions + remaining_definitions

        for definition in field_definitions:
            field_name = f'custom_{definition.id}'
            self.fields[field_name] = self._build_custom_field(definition)
            self.custom_field_names.append(field_name)

            if self.instance.pk:
                try:
                    custom_value = InventoryFieldValue.objects.get(
                        item=self.instance,
                        definition=definition,
                    )
                    self.fields[field_name].initial = self._deserialize_custom_value(definition, custom_value.value)
                except InventoryFieldValue.DoesNotExist:
                    continue

    def _apply_location_default_field_settings(self):
        configured_default_columns = None
        if self.selected_location:
            configured_default_columns = (self.selected_location.view_settings or {}).get('default_columns')

        default_columns = configured_default_columns
        if default_columns is None:
            default_columns = ['sku', 'name', 'quantity', 'unit', 'minimum_stock_level', 'description']

        default_to_form_field = {
            'sku': 'sku',
            'name': 'name',
            'unit': 'unit',
            'minimum_stock_level': 'minimum_stock_level',
            'description': 'description',
        }
        allowed_field_names = [
            default_to_form_field[column]
            for column in default_columns
            if column in default_to_form_field
        ]

        self._show_sku = 'sku' in allowed_field_names
        self._show_name = 'name' in allowed_field_names

        configurable_field_names = list(default_to_form_field.values())
        for field_name in configurable_field_names:
            if field_name in self.fields and field_name not in allowed_field_names:
                del self.fields[field_name]

        self.standard_field_names = [
            field_name for field_name in allowed_field_names if field_name in self.fields
        ]

    def _build_custom_field(self, definition):
        config = definition.config or {}
        common_kwargs = {
            'label': definition.name,
            'required': definition.is_required,
            'help_text': self._build_custom_help_text(definition),
        }

        if definition.field_type == 'number':
            return forms.DecimalField(
                **common_kwargs,
                widget=forms.NumberInput(
                    attrs={
                        'class': 'block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200',
                        'step': config.get('step', '0.01'),
                    }
                ),
            )

        if definition.field_type == 'bool':
            return forms.BooleanField(
                required=False,
                label=definition.name,
                help_text=self._build_custom_help_text(definition),
                widget=forms.CheckboxInput(
                    attrs={'class': 'h-4 w-4 rounded border-gray-300 text-amber-600 focus:ring-amber-500'}
                ),
            )

        if definition.field_type == 'date':
            return forms.DateField(
                **common_kwargs,
                widget=forms.DateInput(
                    attrs={
                        'class': 'block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200',
                        'type': 'date',
                    }
                ),
            )

        if definition.field_type == 'select':
            return forms.ChoiceField(
                **common_kwargs,
                choices=[('', 'Select an option'), *self._choice_options(config.get('options', []))],
                widget=forms.Select(
                    attrs={'class': 'block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200'}
                ),
            )

        return forms.CharField(
            **common_kwargs,
            widget=forms.TextInput(
                attrs={'class': 'block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200'}
            ),
        )

    def _build_custom_help_text(self, definition):
        if definition.location_id:
            return f'Only shown for {definition.location.name}.'
        return 'Available across all inventory locations.'

    def _choice_options(self, raw_options):
        choices = []
        for option in raw_options:
            if isinstance(option, dict):
                value = option.get('value') or option.get('label')
                label = option.get('label') or value
            else:
                value = str(option)
                label = str(option)
            if value:
                choices.append((value, label))
        return choices

    def _deserialize_custom_value(self, definition, value):
        if value in (None, ''):
            return value
        if definition.field_type == 'bool':
            return bool(value)
        return value

    def _serialize_custom_value(self, value):
        if isinstance(value, Decimal):
            return str(value)
        if hasattr(value, 'isoformat'):
            return value.isoformat()
        return value

    def get_custom_fields(self):
        return [self[field_name] for field_name in self.custom_field_names]

    def get_standard_fields(self):
        return [self[field_name] for field_name in self.standard_field_names if field_name in self.fields]

    def _generate_auto_sku(self):
        if not self.organization:
            return 'AUTO-ITEM'

        prefix = 'AUTO'
        if self.selected_location:
            prefix = self.selected_location.code[:10].upper() or 'AUTO'

        for index in range(1, 10000):
            candidate = f'{prefix}-{index:04d}'
            if not InventoryItem.objects.filter(organization=self.organization, sku=candidate).exists():
                return candidate

        return f'{prefix}-ITEM'

    def _generate_auto_name(self, sku):
        for field_name in self.custom_field_names:
            value = self.cleaned_data.get(field_name)
            if value not in (None, '', []):
                return str(value)
        return f'Item {sku}'

    def save(self, commit=True):
        item = super().save(commit=False)

        if not self._show_sku and not item.sku:
            item.sku = self._generate_auto_sku()
        if not self._show_name and not item.name:
            item.name = self._generate_auto_name(item.sku)

        if commit:
            item.save()

        return item

    def save_custom_fields(self, item):
        for field_name in self.custom_field_names:
            definition_id = int(field_name.replace('custom_', ''))
            definition = InventoryFieldDefinition.objects.get(
                id=definition_id,
                organization=item.organization,
            )
            value = self.cleaned_data.get(field_name)

            if definition.field_type != 'bool' and value in (None, '', []):
                InventoryFieldValue.objects.filter(item=item, definition=definition).delete()
                continue

            field_value, _created = InventoryFieldValue.objects.get_or_create(
                organization=item.organization,
                item=item,
                definition=definition,
            )
            field_value.value = self._serialize_custom_value(value)
            field_value.save(update_fields=['value'])


class InventoryLocationForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'h-4 w-4 rounded border-gray-300 text-amber-600 focus:ring-amber-500')
            else:
                field.widget.attrs.setdefault(
                    'class',
                    'block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200',
                )

        self.fields['name'].widget.attrs.setdefault('placeholder', 'Main Warehouse')
        self.fields['code'].widget.attrs.setdefault('placeholder', 'MAIN')
        self.fields['description'].widget.attrs.setdefault('rows', 3)
        self.fields['description'].widget.attrs.setdefault('placeholder', 'Where this location is and what it is used for')
        self.fields['code'].help_text = 'Short unique code used in movement and export reports.'

    class Meta:
        model = InventoryLocation
        fields = ['name', 'code', 'description', 'is_active']


class StockMovementForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        if organization:
            self.fields['item'].queryset = InventoryItem.objects.filter(
                organization=organization,
                is_active=True,
            ).order_by('name')
            self.fields['source_location'].queryset = InventoryLocation.objects.filter(
                organization=organization,
                is_active=True,
            ).order_by('name')
            self.fields['target_location'].queryset = InventoryLocation.objects.filter(
                organization=organization,
                is_active=True,
            ).order_by('name')
            self.fields['reason'].queryset = MovementReason.objects.filter(
                organization=organization,
                is_active=True,
            ).order_by('name')

        for field in self.fields.values():
            field.widget.attrs.setdefault(
                'class',
                'block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200',
            )

        self.fields['item'].empty_label = 'Select an item'
        self.fields['source_location'].required = False
        self.fields['source_location'].empty_label = 'Select source location'
        self.fields['target_location'].required = False
        self.fields['target_location'].empty_label = 'Select target location'
        self.fields['reason'].required = False
        self.fields['reason'].empty_label = 'Optional movement reason'
        self.fields['quantity'].widget.attrs.setdefault('step', '0.01')
        self.fields['quantity'].widget.attrs.setdefault('min', '0.01')
        self.fields['quantity'].widget.attrs.setdefault('placeholder', '0.00')
        self.fields['notes'].widget.attrs.setdefault('rows', 3)
        self.fields['notes'].widget.attrs.setdefault('placeholder', 'Optional notes shown in movement history')
        self.fields['source_location'].help_text = 'Required for Out and Transfer movements.'
        self.fields['target_location'].help_text = 'Required for In, Transfer, and Adjustment movements.'

    class Meta:
        model = StockMovement
        fields = [
            'item',
            'movement_type',
            'quantity',
            'source_location',
            'target_location',
            'reason',
            'notes',
        ]


class MovementReasonForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'h-4 w-4 rounded border-gray-300 text-amber-600 focus:ring-amber-500')
            else:
                field.widget.attrs.setdefault(
                    'class',
                    'block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200',
                )

    class Meta:
        model = MovementReason
        fields = [
            'code',
            'name',
            'description',
            'movement_type',
            'requires_approval',
            'is_active',
        ]


class InventoryFieldDefinitionForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'h-4 w-4 rounded border-gray-300 text-amber-600 focus:ring-amber-500')
            else:
                field.widget.attrs.setdefault(
                    'class',
                    'block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200',
                )

        self.fields['name'].widget.attrs.setdefault('placeholder', 'Batch Number')
        self.fields['key'].widget.attrs.setdefault('placeholder', 'batch_number')
        self.fields['location'].required = False
        self.fields['location'].empty_label = 'All locations'
        self.fields['location'].help_text = 'Leave blank to make this field available everywhere. Choose a location to scope it to just that location.'

        if organization:
            self.fields['location'].queryset = InventoryLocation.objects.filter(
                organization=organization,
                is_active=True,
            ).order_by('name')

    class Meta:
        model = InventoryFieldDefinition
        fields = [
            'location',
            'name',
            'key',
            'field_type',
            'config',
            'is_required',
            'is_active',
        ]


class LocationViewSettingsForm(forms.Form):
    DEFAULT_COLUMN_CHOICES = [
        ('sku', 'SKU'),
        ('name', 'Item Name'),
        ('quantity', 'Quantity'),
        ('unit', 'Unit'),
        ('minimum_stock_level', 'Minimum Stock Level'),
        ('status', 'Status'),
        ('description', 'Description'),
    ]

    default_columns = forms.MultipleChoiceField(
        choices=DEFAULT_COLUMN_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='Uncheck default fields you want to hide for this location.',
    )
    custom_columns = forms.MultipleChoiceField(
        choices=[],
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='Select custom fields to show instead of hidden default fields.',
    )

    def __init__(self, *args, **kwargs):
        custom_field_definitions = kwargs.pop('custom_field_definitions', [])
        super().__init__(*args, **kwargs)

        self.fields['custom_columns'].choices = [
            (field.key, f'{field.name} ({field.key})')
            for field in custom_field_definitions
            if field.is_active
        ]
        self.fields['default_columns'].choices = self._reorder_choices(
            self.fields['default_columns'].choices,
            self._selected_values('default_columns'),
        )
        self.fields['custom_columns'].choices = self._reorder_choices(
            self.fields['custom_columns'].choices,
            self._selected_values('custom_columns'),
        )

    def _selected_values(self, field_name):
        if self.is_bound:
            return self.data.getlist(field_name)

        initial_value = self.initial.get(field_name, [])
        return list(initial_value or [])

    def _reorder_choices(self, choices, ordered_values):
        choice_map = {value: label for value, label in choices}
        ordered_choices = [
            (value, choice_map[value])
            for value in ordered_values
            if value in choice_map
        ]
        remaining_choices = [
            (value, label)
            for value, label in choices
            if value not in set(ordered_values)
        ]
        return ordered_choices + remaining_choices

    def clean(self):
        return super().clean()
