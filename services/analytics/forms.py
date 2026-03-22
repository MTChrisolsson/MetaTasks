from django import forms
from .models import StatistikJob


class StatistikLiteForm(forms.Form):
    """Lightweight form for CITK vs Wayke-only comparison (no inventory file)."""

    wayke = forms.FileField(
        label='Wayke Data',
        help_text='CSV file from Wayke API',
    )
    citk = forms.FileField(
        label='CITK Data',
        help_text='Excel file with vehicle matching data',
    )
    notes = forms.FileField(
        label='Notes (Optional)',
        required=False,
        help_text='JSON/CSV file with custom notes',
    )
    citk_sheet = forms.CharField(
        label='CITK Sheet Name',
        initial='Sheet1',
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'block w-full text-sm text-gray-700 border border-gray-300 rounded-lg p-2',
            'placeholder': 'e.g., Sheet1',
        }),
    )


class StatistikUploadForm(forms.ModelForm):
    inventory = forms.FileField(
        label='Inventory Data',
        help_text='Excel file with vehicle inventory'
    )
    wayke = forms.FileField(
        label='Wayke Data',
        help_text='CSV file from Wayke API'
    )
    citk = forms.FileField(
        label='CITK Data',
        help_text='Excel file with vehicle matching data'
    )
    notes = forms.FileField(
        label='Notes (Optional)',
        required=False,
        help_text='JSON/CSV file with custom notes'
    )
    
    class Meta:
        model = StatistikJob
        fields = ['inventory_sheet', 'citk_sheet', 'photo_min_urls']
        widgets = {
            'inventory_sheet': forms.TextInput(attrs={
                'class': 'block w-full text-sm text-gray-700 border border-gray-300 rounded-lg p-2',
                'placeholder': 'e.g., toyota lager'
            }),
            'citk_sheet': forms.TextInput(attrs={
                'class': 'block w-full text-sm text-gray-700 border border-gray-300 rounded-lg p-2',
                'placeholder': 'e.g., Sheet1'
            }),
            'photo_min_urls': forms.NumberInput(attrs={
                'class': 'block w-full text-sm text-gray-700 border border-gray-300 rounded-lg p-2',
                'min': 1
            }),
        }