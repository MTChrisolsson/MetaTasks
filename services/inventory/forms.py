from django import forms

from .models import (
    InventoryFieldDefinition,
    InventoryItem,
    InventoryLocation,
    MovementReason,
    StockMovement,
)


class InventoryItemForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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

    class Meta:
        model = InventoryFieldDefinition
        fields = [
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

    def clean(self):
        cleaned_data = super().clean()
        default_columns = cleaned_data.get('default_columns', [])
        custom_columns = cleaned_data.get('custom_columns', [])

        if not default_columns and not custom_columns:
            raise forms.ValidationError('Select at least one default or custom field to display.')

        return cleaned_data
