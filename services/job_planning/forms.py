from django import forms
from django.contrib.auth import get_user_model

from .models import Project, Task, Milestone, ProjectComment, TaskComment


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = [
            'name', 'description', 'status', 'priority', 'start_date',
            'end_date', 'budget', 'progress_percentage', 'manager'
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 4}),
            'progress_percentage': forms.NumberInput(attrs={'min': 0, 'max': 100}),
            'budget': forms.NumberInput(attrs={'step': '0.01', 'min': 0}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            # Limit manager choices to organization members
            self.fields['manager'].queryset = get_user_model().objects.filter(
                mediap_profile__organization=organization
            )


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = [
            'title', 'description', 'status', 'priority', 'assigned_to',
            'estimated_hours', 'actual_hours', 'start_date', 'due_date', 'parent_task'
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'estimated_hours': forms.NumberInput(attrs={'step': '0.5', 'min': 0}),
            'actual_hours': forms.NumberInput(attrs={'step': '0.5', 'min': 0}),
        }

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project:
            # Limit assigned_to choices to project organization members
            self.fields['assigned_to'].queryset = get_user_model().objects.filter(
                mediap_profile__organization=project.organization
            )
            # Limit parent_task choices to other tasks in this project
            if self.instance:
                # Exclude self and descendants for parent_task
                self.fields['parent_task'].queryset = project.tasks.exclude(
                    id=self.instance.id
                ).exclude(
                    parent_task=self.instance
                )
            else:
                self.fields['parent_task'].queryset = project.tasks.all()


class MilestoneForm(forms.ModelForm):
    class Meta:
        model = Milestone
        fields = ['title', 'description', 'due_date']
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class ProjectCommentForm(forms.ModelForm):
    class Meta:
        model = ProjectComment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Add a comment...'}),
        }


class TaskCommentForm(forms.ModelForm):
    class Meta:
        model = TaskComment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Add a comment...'}),
        }