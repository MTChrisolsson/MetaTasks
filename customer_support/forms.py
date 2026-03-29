from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.text import slugify

from .models import KBArticle, KBCategory, SupportTag, SupportTicket, SupportTicketComment


def _support_setting(name, default):
    return getattr(settings, 'CUSTOMER_SUPPORT', {}).get(name, default)


class SupportTicketForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = ['title', 'description', 'category', 'priority', 'attachment']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'w-full rounded-lg border-slate-300'}),
            'description': forms.Textarea(attrs={'rows': 5, 'class': 'w-full rounded-lg border-slate-300'}),
            'category': forms.Select(attrs={'class': 'w-full rounded-lg border-slate-300'}),
            'priority': forms.Select(attrs={'class': 'w-full rounded-lg border-slate-300'}),
            'attachment': forms.ClearableFileInput(attrs={'class': 'w-full rounded-lg border-slate-300'}),
        }

    def clean_attachment(self):
        attachment = self.cleaned_data.get('attachment')
        if not attachment:
            return attachment

        max_size_mb = _support_setting('MAX_ATTACHMENT_SIZE_MB', 10)
        allowed_extensions = _support_setting(
            'ALLOWED_ATTACHMENT_EXTENSIONS',
            ['.pdf', '.jpg', '.png', '.doc', '.docx'],
        )

        if attachment.size > (max_size_mb * 1024 * 1024):
            raise forms.ValidationError(f'Attachment exceeds {max_size_mb} MB limit.')

        filename = attachment.name.lower()
        if not any(filename.endswith(ext.lower()) for ext in allowed_extensions):
            raise forms.ValidationError('Unsupported attachment file type.')
        return attachment


class SupportTicketCommentForm(forms.ModelForm):
    class Meta:
        model = SupportTicketComment
        fields = ['comment_text', 'is_internal', 'attachment']
        widgets = {
            'comment_text': forms.Textarea(attrs={'rows': 3, 'class': 'w-full rounded-lg border-slate-300'}),
            'is_internal': forms.CheckboxInput(attrs={'class': 'rounded border-slate-300'}),
            'attachment': forms.ClearableFileInput(attrs={'class': 'w-full rounded-lg border-slate-300'}),
        }


class SupportTicketUpdateForm(forms.ModelForm):
    tags = forms.ModelMultipleChoiceField(
        queryset=SupportTag.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'w-full rounded-lg border-slate-300'}),
    )

    class Meta:
        model = SupportTicket
        fields = ['status', 'priority', 'assigned_to', 'tags']
        widgets = {
            'status': forms.Select(attrs={'class': 'w-full rounded-lg border-slate-300'}),
            'priority': forms.Select(attrs={'class': 'w-full rounded-lg border-slate-300'}),
            'assigned_to': forms.Select(attrs={'class': 'w-full rounded-lg border-slate-300'}),
        }

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)
        user_model = get_user_model()

        if organization:
            self.fields['assigned_to'].queryset = user_model.objects.filter(
                mediap_profile__organization=organization,
                is_active=True,
            ).order_by('first_name', 'last_name', 'username')
            self.fields['tags'].queryset = SupportTag.objects.all().order_by('name')


class SupportSearchForm(forms.Form):
    search_query = forms.CharField(required=False)
    status_filter = forms.ChoiceField(required=False, choices=[('', 'All')] + SupportTicket.STATUS_CHOICES)
    priority_filter = forms.ChoiceField(required=False, choices=[('', 'All')] + SupportTicket.PRIORITY_CHOICES)
    org_filter = forms.IntegerField(required=False)


class CustomerTicketCreateForm(forms.ModelForm):
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
    ]

    priority = forms.ChoiceField(choices=PRIORITY_CHOICES, initial='medium')

    class Meta:
        model = SupportTicket
        fields = ['title', 'description', 'category', 'priority', 'attachment']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'w-full rounded-lg border-slate-300'}),
            'description': forms.Textarea(attrs={'rows': 5, 'class': 'w-full rounded-lg border-slate-300'}),
            'category': forms.Select(attrs={'class': 'w-full rounded-lg border-slate-300'}),
            'attachment': forms.ClearableFileInput(attrs={'class': 'w-full rounded-lg border-slate-300'}),
        }


class KBArticleForm(forms.ModelForm):
    class Meta:
        model = KBArticle
        fields = ['title', 'slug', 'category', 'excerpt', 'content', 'status', 'is_public']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'w-full rounded-lg border-slate-300'}),
            'slug': forms.TextInput(attrs={'class': 'w-full rounded-lg border-slate-300 font-mono text-sm'}),
            'excerpt': forms.Textarea(attrs={'rows': 2, 'class': 'w-full rounded-lg border-slate-300'}),
            'content': forms.Textarea(attrs={'rows': 14, 'class': 'w-full rounded-lg border-slate-300 font-mono text-sm'}),
            'status': forms.Select(attrs={'class': 'w-full rounded-lg border-slate-300'}),
            'is_public': forms.CheckboxInput(attrs={'class': 'rounded border-slate-300'}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields['category'].queryset = KBCategory.objects.filter(organization=organization)
        else:
            self.fields['category'].queryset = KBCategory.objects.none()
        self.fields['category'].required = False
        self.fields['slug'].required = False

    def clean_slug(self):
        slug = self.cleaned_data.get('slug', '').strip()
        if not slug:
            title = self.cleaned_data.get('title', '')
            slug = slugify(title)
        return slug

