from django import forms
from django.contrib.auth.forms import UserCreationForm
from core.models import Organization, UserProfile
from .models import CustomUser

class RegistrationForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
            'placeholder': 'Enter your email address'
        })
    )
    
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
            'placeholder': 'First name'
        })
    )
    
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
            'placeholder': 'Last name'
        })
    )
    
    referral_source = forms.ChoiceField(
        choices=CustomUser.REFERRAL_SOURCES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6'
        }),
        label="How did you hear about us?"
    )
    
    team_size = forms.ChoiceField(
        choices=CustomUser.TEAM_SIZES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6'
        }),
        label="What's the size of your team?"
    )

    job_title = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
            'placeholder': 'Your job title'
        })
    )


    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ('username', 'first_name', 'last_name', 'email', 'phone_number', 'job_title', 'password1', 'password2', 'referral_source', 'team_size')
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Style the default fields
        self.fields['username'].widget.attrs.update({
            'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
            'placeholder': 'Choose a username'
        })
        self.fields['password1'].widget.attrs.update({
            'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
            'placeholder': 'Create a password'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
            'placeholder': 'Confirm your password'
        })


    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.referral_source = self.cleaned_data['referral_source']
        user.team_size = self.cleaned_data['team_size']
        user.phone_number = self.cleaned_data['phone_number']
        user.job_title = self.cleaned_data['job_title']
        if commit:
            user.save()
        return user


class OrganizationCreationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ['name', 'description', 'organization_type']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
                'placeholder': 'Your organization name'
            }),
            'description': forms.Textarea(attrs={
                'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
                'placeholder': 'Brief description of your organization (optional)',
                'rows': 3
            }),
            'organization_type': forms.Select(attrs={
                'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6'
            }),
        }
        labels = {
            'name': "Organization Name",
            'description': "Description",
            'organization_type': "Organization Type",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make description optional
        self.fields['description'].required = False
        
        # Set default to business for business registration
        self.fields['organization_type'].initial = 'business'

    def clean_name(self):
        """Ensure organization name is not empty or just whitespace"""
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError('Organization name cannot be empty.')
        return name


class InviteMemberForm(forms.Form):
    email = forms.EmailField(
        label="Email of the person to invite",
        widget=forms.EmailInput(attrs={
            'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
            'placeholder': 'Enter email address'
        })
    )
    
    role = forms.ChoiceField(
        choices=[
            ('team_member', 'Team Member'),
            ('team_leader', 'Team Leader'),
            ('admin', 'Admin'),
        ],
        initial='team_member',
        widget=forms.Select(attrs={
            'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6'
        }),
        label="Role"
    )


class UserProfileSetupForm(forms.ModelForm):
    """Form for setting up a user's profile during onboarding"""
    
    # Organization selection - user can choose to create new or join existing
    organization_choice = forms.ChoiceField(
        choices=[
            ('create', 'Create a new organization'),
            ('join', 'Join an existing organization'),
        ],
        initial='create',
        widget=forms.RadioSelect(attrs={'class': 'radio-input'}),
        label="Organization Setup"
    )
    
    # For creating new organization
    new_org_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
            'placeholder': 'Enter organization name'
        }),
        label="Organization Name"
    )
    
    new_org_type = forms.ChoiceField(
        choices=[
            ('personal', 'Personal Workspace'),
            ('business', 'Business Organization'),
        ],
        initial='business',
        required=False,
        widget=forms.Select(attrs={
            'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6'
        }),
        label="Organization Type"
    )
    
    # For joining existing organization (if any exist)
    existing_org = forms.ModelChoiceField(
        queryset=Organization.objects.filter(is_active=True),
        required=False,
        empty_label="Select an organization",
        widget=forms.Select(attrs={
            'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6'
        }),
        label="Select Organization"
    )
    
    class Meta:
        model = UserProfile
        fields = ['title', 'department', 'location', 'timezone', 'bio', 'phone', 'email_notifications']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
                'placeholder': 'e.g. Software Engineer, Project Manager'
            }),
            'department': forms.TextInput(attrs={
                'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
                'placeholder': 'e.g. Engineering, Marketing, Sales'
            }),
            'location': forms.TextInput(attrs={
                'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
                'placeholder': 'e.g. New York, NY or Remote'
            }),
            'timezone': forms.Select(attrs={
                'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6'
            }),
            'bio': forms.Textarea(attrs={
                'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
                'placeholder': 'Tell us a bit about yourself...',
                'rows': 3
            }),
            'phone': forms.TextInput(attrs={
                'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6',
                'placeholder': 'e.g. +1 (555) 123-4567'
            }),
            'email_notifications': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-blue-600 focus:ring-blue-600 border-gray-300 rounded'
            }),
        }
        labels = {
            'title': 'Job Title',
            'department': 'Department',
            'location': 'Location',
            'timezone': 'Timezone',
            'bio': 'Bio',
            'phone': 'Phone Number',
            'email_notifications': 'Receive email notifications',
        }
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Set timezone choices
        self.fields['timezone'].choices = [
            ('UTC', 'UTC'),
            ('America/New_York', 'Eastern Time'),
            ('America/Chicago', 'Central Time'),
            ('America/Denver', 'Mountain Time'),
            ('America/Los_Angeles', 'Pacific Time'),
            ('Europe/London', 'London'),
            ('Europe/Paris', 'Paris'),
            ('Asia/Tokyo', 'Tokyo'),
            ('Australia/Sydney', 'Sydney'),
        ]
        
        # Make bio and other fields optional
        self.fields['bio'].required = False
        self.fields['title'].required = False
        self.fields['department'].required = False
        self.fields['location'].required = False
        self.fields['phone'].required = False
        
        # Check if there are existing organizations to join
        if not Organization.objects.filter(is_active=True).exists():
            # No existing orgs, hide join option
            self.fields['organization_choice'].choices = [('create', 'Create a new organization')]
            self.fields['existing_org'].widget = forms.HiddenInput()
        else:
            # Show both options
            self.fields['organization_choice'].choices = [
                ('create', 'Create a new organization'),
                ('join', 'Join an existing organization'),
            ]
    
    def clean(self):
        cleaned_data = super().clean()
        choice = cleaned_data.get('organization_choice')
        
        if choice == 'create':
            if not cleaned_data.get('new_org_name'):
                raise forms.ValidationError("Organization name is required when creating a new organization.")
            if not cleaned_data.get('new_org_type'):
                raise forms.ValidationError("Organization type is required when creating a new organization.")
        elif choice == 'join':
            if not cleaned_data.get('existing_org'):
                raise forms.ValidationError("Please select an organization to join.")
        
        return cleaned_data
