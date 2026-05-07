from django.urls import path
from . import views

app_name = 'job_planning'

urlpatterns = [
    path('', views.project_list, name='project-list'),
    path('projects/', views.project_list, name='project-list'),
    path('projects/create/', views.project_create, name='project-create'),
    path('projects/<int:project_id>/', views.project_detail, name='project-detail'),
    path('projects/<int:project_id>/edit/', views.project_edit, name='project-edit'),
    path('projects/<int:project_id>/delete/', views.project_delete, name='project-delete'),
    path('projects/<int:project_id>/tasks/create/', views.task_create, name='task-create'),
    path('projects/<int:project_id>/tasks/<int:task_id>/', views.task_detail, name='task-detail'),
    path('projects/<int:project_id>/tasks/<int:task_id>/edit/', views.task_edit, name='task-edit'),
    path('projects/<int:project_id>/tasks/<int:task_id>/delete/', views.task_delete, name='task-delete'),
    path('projects/<int:project_id>/milestones/create/', views.milestone_create, name='milestone-create'),
    path('projects/<int:project_id>/milestones/<int:milestone_id>/edit/', views.milestone_edit, name='milestone-edit'),
    path('projects/<int:project_id>/milestones/<int:milestone_id>/delete/', views.milestone_delete, name='milestone-delete'),
    path('projects/<int:project_id>/comments/', views.project_add_comment, name='project-add-comment'),
    path('projects/<int:project_id>/tasks/<int:task_id>/comments/', views.task_add_comment, name='task-add-comment'),
]