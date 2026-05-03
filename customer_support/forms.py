from django import forms
from .models import SupportTicket, SupportTicketComment

class SupportTicketForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = ['title', 'description', 'priority', 'category', 'attachment']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Issue summary'}),
            'description': forms.Textarea(attrs={'class': 'form-textarea', 'rows': 4}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
        }

class SupportTicketUpdateForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = ['status', 'priority', 'assigned_to']

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)
        if organization:
            # Filter assigned_to to only show members of the organization
            from core.models import UserProfile
            self.fields['assigned_to'].queryset = UserProfile.objects.filter(organization=organization)

class SupportTicketCommentForm(forms.ModelForm):
    class Meta:
        model = SupportTicketComment
        fields = ['comment_text', 'is_internal', 'attachment']
        widgets = {
            'comment_text': forms.Textarea(attrs={'class': 'form-textarea', 'rows': 3, 'placeholder': 'Type your message...'}),
        }

class SupportSearchForm(forms.Form):
    search_query = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Search tickets...',
            'class': 'form-input'
        })
    )
    status_filter = forms.ChoiceField(
        choices=[('', 'All Statuses')] + SupportTicket.STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )