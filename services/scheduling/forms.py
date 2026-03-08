from django import forms
from django.utils import timezone
from datetime import timedelta
from .models import ResourceScheduleRule, SchedulableResource, BookingRequest
from core.models import UserProfile


class BookingForm(forms.ModelForm):
    """Form for creating and editing bookings"""
    
    class Meta:
        model = BookingRequest
        fields = [
            'title', 'description', 'resource', 'requested_start', 
            'requested_end', 'priority'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-green-500 focus:border-green-500 sm:text-sm',
                'placeholder': 'Enter booking title'
            }),
            'description': forms.Textarea(attrs={
                'class': 'mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-green-500 focus:border-green-500 sm:text-sm',
                'rows': 4,
                'placeholder': 'Enter booking description (optional)'
            }),
            'resource': forms.Select(attrs={
                'class': 'mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-green-500 focus:border-green-500 sm:text-sm'
            }),
            'requested_start': forms.DateTimeInput(attrs={
                'class': 'mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-green-500 focus:border-green-500 sm:text-sm',
                'type': 'datetime-local'
            }, format='%Y-%m-%dT%H:%M'),
            'requested_end': forms.DateTimeInput(attrs={
                'class': 'mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-green-500 focus:border-green-500 sm:text-sm',
                'type': 'datetime-local'
            }, format='%Y-%m-%dT%H:%M'),
            'priority': forms.Select(attrs={
                'class': 'mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-green-500 focus:border-green-500 sm:text-sm'
            })
        }
    
    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)
        
        if organization:
            self.fields['resource'].queryset = SchedulableResource.objects.filter(
                organization=organization,
                is_active=True
            )
        
        # Set default times
        if not self.instance.pk:
            now = timezone.now()
            self.fields['requested_start'].initial = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            self.fields['requested_end'].initial = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=3)
    
    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('requested_start')
        end_time = cleaned_data.get('requested_end')
        
        if start_time and end_time:
            if start_time >= end_time:
                raise forms.ValidationError("End time must be after start time")
            
            if start_time < timezone.now():
                raise forms.ValidationError("Start time cannot be in the past")
        
        return cleaned_data


class ResourceForm(forms.ModelForm):
    """Form for creating and editing resources"""
    
    working_days = forms.MultipleChoiceField(
        choices=[
            (0, 'Monday'),
            (1, 'Tuesday'),
            (2, 'Wednesday'),
            (3, 'Thursday'),
            (4, 'Friday'),
            (5, 'Saturday'),
            (6, 'Sunday'),
        ],
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'space-y-2'
        }),
        initial=[0, 1, 2, 3, 4],  # Mon-Fri default
        required=False
    )
    
    start_hour = forms.IntegerField(
        min_value=0,
        max_value=23,
        initial=8,
        widget=forms.NumberInput(attrs={
            'class': 'mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-green-500 focus:border-green-500 sm:text-sm'
        })
    )
    
    end_hour = forms.IntegerField(
        min_value=0,
        max_value=23,
        initial=18,
        widget=forms.NumberInput(attrs={
            'class': 'mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-green-500 focus:border-green-500 sm:text-sm'
        })
    )

    auto_approve_bookings = forms.BooleanField(
        label='Auto-approve all bookings for this resource',
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 text-green-600 focus:ring-green-500 border-gray-300 rounded'
        })
    )
    
    class Meta:
        model = SchedulableResource
        fields = [
            'name', 'resource_type', 'description', 
            'max_concurrent_bookings'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-green-500 focus:border-green-500 sm:text-sm',
                'placeholder': 'Enter resource name'
            }),
            'resource_type': forms.Select(attrs={
                'class': 'mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-green-500 focus:border-green-500 sm:text-sm'
            }),
            'description': forms.Textarea(attrs={
                'class': 'mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-green-500 focus:border-green-500 sm:text-sm',
                'rows': 4,
                'placeholder': 'Enter resource description (optional)'
            }),
            'max_concurrent_bookings': forms.NumberInput(attrs={
                'class': 'mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-green-500 focus:border-green-500 sm:text-sm',
                'min': 1
            })
        }
    
    def __init__(self, *args, **kwargs):
        instance = kwargs.get('instance')
        super().__init__(*args, **kwargs)
        
        # Load existing availability rules if editing
        if instance and instance.availability_rules:
            self.fields['working_days'].initial = instance.availability_rules.get('working_days', [0, 1, 2, 3, 4])
            self.fields['start_hour'].initial = instance.availability_rules.get('start_hour', 8)
            self.fields['end_hour'].initial = instance.availability_rules.get('end_hour', 18)
    
    def save(self, commit=True):
        instance = super().save(commit=False)
    
        # Set availability rules from form fields
        availability_rules = instance.availability_rules or {}
        availability_rules.update({
            'working_days': [int(day) for day in self.cleaned_data['working_days']],
            'start_hour': self.cleaned_data['start_hour'],
            'end_hour': self.cleaned_data['end_hour']
        })
        instance.availability_rules = availability_rules
    
        if commit:
            instance.save()
        
            # Create auto-approval rule if checkbox was checked
            if self.cleaned_data.get('auto_approve_bookings'):
                ResourceScheduleRule.objects.get_or_create(
                    resource=instance,
                    rule_type='auto_approval',  # Changed from 'auto_approve'
                    defaults={
                        'is_active': True,
                        'rule_config': {'auto_confirm': True}
                    }
                )
    
        return instance