from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.decorators import require_organization_access
from .models import Project, Task, Milestone, ProjectComment, TaskComment
from .forms import ProjectForm, TaskForm, MilestoneForm, ProjectCommentForm, TaskCommentForm


@login_required
@require_organization_access
def project_list(request):
    """List all projects for the user's organization"""
    profile = request.user.mediap_profile
    organization = profile.organization

    projects = Project.objects.filter(organization=organization).select_related('manager', 'created_by')

    # Filter by status
    status_filter = request.GET.get('status')
    if status_filter:
        projects = projects.filter(status=status_filter)

    # Search
    search_query = request.GET.get('search', '').strip()
    if search_query:
        projects = projects.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    context = {
        'profile': profile,
        'projects': projects,
        'status_filter': status_filter,
        'search_query': search_query,
        'page_title': 'Projects',
    }
    return render(request, 'job_planning/project_list.html', context)


@login_required
@require_organization_access
def project_create(request):
    """Create a new project"""
    profile = request.user.mediap_profile
    organization = profile.organization

    if request.method == 'POST':
        form = ProjectForm(request.POST, organization=organization)
        if form.is_valid():
            project = form.save(commit=False)
            project.organization = organization
            project.created_by = request.user
            project.save()
            messages.success(request, f'Project "{project.name}" created successfully.')
            return redirect('job_planning:project-detail', project_id=project.id)
    else:
        form = ProjectForm(organization=organization)

    context = {
        'profile': profile,
        'form': form,
        'page_title': 'Create Project',
    }
    return render(request, 'job_planning/project_form.html', context)


@login_required
@require_organization_access
def project_detail(request, project_id):
    """View project details"""
    profile = request.user.mediap_profile
    organization = profile.organization

    project = get_object_or_404(
        Project,
        id=project_id,
        organization=organization
    )

    tasks = project.tasks.select_related('assigned_to', 'created_by').order_by('due_date', 'priority')
    milestones = project.milestones.order_by('due_date')
    comments = project.comments.select_related('author').order_by('-created_at')

    # Calculate project stats
    total_tasks = tasks.count()
    completed_tasks = tasks.filter(status='done').count()
    overdue_tasks = tasks.filter(due_date__lt=timezone.now().date(), status__in=['todo', 'in_progress']).count()

    context = {
        'profile': profile,
        'project': project,
        'tasks': tasks,
        'milestones': milestones,
        'comments': comments,
        'total_tasks': total_tasks,
        'completed_tasks': completed_tasks,
        'overdue_tasks': overdue_tasks,
        'completion_percentage': (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0,
        'page_title': project.name,
    }
    return render(request, 'job_planning/project_detail.html', context)


@login_required
@require_organization_access
def project_edit(request, project_id):
    """Edit a project"""
    profile = request.user.mediap_profile
    organization = profile.organization

    project = get_object_or_404(
        Project,
        id=project_id,
        organization=organization
    )

    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project, organization=organization)
        if form.is_valid():
            form.save()
            messages.success(request, f'Project "{project.name}" updated successfully.')
            return redirect('job_planning:project-detail', project_id=project.id)
    else:
        form = ProjectForm(instance=project, organization=organization)

    context = {
        'profile': profile,
        'project': project,
        'form': form,
        'page_title': f'Edit {project.name}',
    }
    return render(request, 'job_planning/project_form.html', context)


@login_required
@require_organization_access
def project_delete(request, project_id):
    """Delete a project"""
    profile = request.user.mediap_profile
    organization = profile.organization

    project = get_object_or_404(
        Project,
        id=project_id,
        organization=organization
    )

    if request.method == 'POST':
        project_name = project.name
        project.delete()
        messages.success(request, f'Project "{project_name}" deleted successfully.')
        return redirect('job_planning:project-list')

    context = {
        'profile': profile,
        'project': project,
        'page_title': f'Delete {project.name}',
    }
    return render(request, 'job_planning/project_confirm_delete.html', context)


@login_required
@require_organization_access
def task_create(request, project_id):
    """Create a new task"""
    profile = request.user.mediap_profile
    organization = profile.organization

    project = get_object_or_404(
        Project,
        id=project_id,
        organization=organization
    )

    if request.method == 'POST':
        form = TaskForm(request.POST, project=project)
        if form.is_valid():
            task = form.save(commit=False)
            task.project = project
            task.created_by = request.user
            task.save()
            messages.success(request, f'Task "{task.title}" created successfully.')
            return redirect('job_planning:project-detail', project_id=project.id)
    else:
        form = TaskForm(project=project)

    context = {
        'profile': profile,
        'project': project,
        'form': form,
        'page_title': f'Create Task for {project.name}',
    }
    return render(request, 'job_planning/task_form.html', context)


@login_required
@require_organization_access
def task_detail(request, project_id, task_id):
    """View task details"""
    profile = request.user.mediap_profile
    organization = profile.organization

    project = get_object_or_404(
        Project,
        id=project_id,
        organization=organization
    )
    task = get_object_or_404(
        Task,
        id=task_id,
        project=project
    )

    comments = task.comments.select_related('author').order_by('-created_at')
    subtasks = task.subtasks.select_related('assigned_to', 'created_by')

    context = {
        'profile': profile,
        'project': project,
        'task': task,
        'comments': comments,
        'subtasks': subtasks,
        'page_title': task.title,
    }
    return render(request, 'job_planning/task_detail.html', context)


@login_required
@require_organization_access
def task_edit(request, project_id, task_id):
    """Edit a task"""
    profile = request.user.mediap_profile
    organization = profile.organization

    project = get_object_or_404(
        Project,
        id=project_id,
        organization=organization
    )
    task = get_object_or_404(
        Task,
        id=task_id,
        project=project
    )

    if request.method == 'POST':
        form = TaskForm(request.POST, instance=task, project=project)
        if form.is_valid():
            form.save()
            messages.success(request, f'Task "{task.title}" updated successfully.')
            return redirect('job_planning:task-detail', project_id=project.id, task_id=task.id)
    else:
        form = TaskForm(instance=task, project=project)

    context = {
        'profile': profile,
        'project': project,
        'task': task,
        'form': form,
        'page_title': f'Edit {task.title}',
    }
    return render(request, 'job_planning/task_form.html', context)


@login_required
@require_organization_access
def task_delete(request, project_id, task_id):
    """Delete a task"""
    profile = request.user.mediap_profile
    organization = profile.organization

    project = get_object_or_404(
        Project,
        id=project_id,
        organization=organization
    )
    task = get_object_or_404(
        Task,
        id=task_id,
        project=project
    )

    if request.method == 'POST':
        task_title = task.title
        task.delete()
        messages.success(request, f'Task "{task_title}" deleted successfully.')
        return redirect('job_planning:project-detail', project_id=project.id)

    context = {
        'profile': profile,
        'project': project,
        'task': task,
        'page_title': f'Delete {task.title}',
    }
    return render(request, 'job_planning/task_confirm_delete.html', context)


@login_required
@require_organization_access
def milestone_create(request, project_id):
    """Create a new milestone"""
    profile = request.user.mediap_profile
    organization = profile.organization

    project = get_object_or_404(
        Project,
        id=project_id,
        organization=organization
    )

    if request.method == 'POST':
        form = MilestoneForm(request.POST)
        if form.is_valid():
            milestone = form.save(commit=False)
            milestone.project = project
            milestone.created_by = request.user
            milestone.save()
            messages.success(request, f'Milestone "{milestone.title}" created successfully.')
            return redirect('job_planning:project-detail', project_id=project.id)
    else:
        form = MilestoneForm()

    context = {
        'profile': profile,
        'project': project,
        'form': form,
        'page_title': f'Create Milestone for {project.name}',
    }
    return render(request, 'job_planning/milestone_form.html', context)


@login_required
@require_organization_access
def milestone_edit(request, project_id, milestone_id):
    """Edit a milestone"""
    profile = request.user.mediap_profile
    organization = profile.organization

    project = get_object_or_404(
        Project,
        id=project_id,
        organization=organization
    )
    milestone = get_object_or_404(
        Milestone,
        id=milestone_id,
        project=project
    )

    if request.method == 'POST':
        form = MilestoneForm(request.POST, instance=milestone)
        if form.is_valid():
            form.save()
            messages.success(request, f'Milestone "{milestone.title}" updated successfully.')
            return redirect('job_planning:project-detail', project_id=project.id)
    else:
        form = MilestoneForm(instance=milestone)

    context = {
        'profile': profile,
        'project': project,
        'milestone': milestone,
        'form': form,
        'page_title': f'Edit {milestone.title}',
    }
    return render(request, 'job_planning/milestone_form.html', context)


@login_required
@require_organization_access
def milestone_delete(request, project_id, milestone_id):
    """Delete a milestone"""
    profile = request.user.mediap_profile
    organization = profile.organization

    project = get_object_or_404(
        Project,
        id=project_id,
        organization=organization
    )
    milestone = get_object_or_404(
        Milestone,
        id=milestone_id,
        project=project
    )

    if request.method == 'POST':
        milestone_title = milestone.title
        milestone.delete()
        messages.success(request, f'Milestone "{milestone_title}" deleted successfully.')
        return redirect('job_planning:project-detail', project_id=project.id)

    context = {
        'profile': profile,
        'project': project,
        'milestone': milestone,
        'page_title': f'Delete {milestone.title}',
    }
    return render(request, 'job_planning/milestone_confirm_delete.html', context)


@login_required
@require_organization_access
def project_add_comment(request, project_id):
    """Add a comment to a project"""
    profile = request.user.mediap_profile
    organization = profile.organization

    project = get_object_or_404(
        Project,
        id=project_id,
        organization=organization
    )

    if request.method == 'POST':
        form = ProjectCommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.project = project
            comment.author = request.user
            comment.save()
            messages.success(request, 'Comment added successfully.')
            return redirect('job_planning:project-detail', project_id=project.id)
    else:
        form = ProjectCommentForm()

    context = {
        'profile': profile,
        'project': project,
        'form': form,
        'page_title': f'Add Comment to {project.name}',
    }
    return render(request, 'job_planning/project_add_comment.html', context)


@login_required
@require_organization_access
def task_add_comment(request, project_id, task_id):
    """Add a comment to a task"""
    profile = request.user.mediap_profile
    organization = profile.organization

    project = get_object_or_404(
        Project,
        id=project_id,
        organization=organization
    )
    task = get_object_or_404(
        Task,
        id=task_id,
        project=project
    )

    if request.method == 'POST':
        form = TaskCommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.task = task
            comment.author = request.user
            comment.save()
            messages.success(request, 'Comment added successfully.')
            return redirect('job_planning:task-detail', project_id=project.id, task_id=task.id)
    else:
        form = TaskCommentForm()

    context = {
        'profile': profile,
        'project': project,
        'task': task,
        'form': form,
        'page_title': f'Add Comment to {task.title}',
    }
    return render(request, 'job_planning/task_add_comment.html', context)