from django.urls import path
from . import views

app_name = 'staff_panel'

urlpatterns = [
    path('', views.staff_panel_dashboard, name='dashboard'),
    path('users/create/', views.create_staff_user, name='create_staff_user'),
    # User Management
    path('users/', views.user_management, name='user_management'),
    path('users/<int:user_id>/', views.user_detail, name='user_detail'),
    path('users/<int:user_id>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:user_id>/activity/', views.user_activity, name='user_activity'),
    path('users/<int:user_id>/toggle-status/', views.toggle_user_status, name='toggle_user_status'),
    path('users/export/', views.export_users, name='export_users'),
    path('organization/', views.organization_settings, name='organization_settings'),
    path('analytics/', views.user_analytics, name='user_analytics'),
    path('teams/', views.team_management, name='team_management'),
    path('teams/search-users/', views.search_users, name='search_users'),
    path('teams/<int:team_id>/add-member/', views.add_team_member, name='add_team_member'),
    path('teams/<int:team_id>/remove-member/', views.remove_team_member, name='remove_team_member'),
    path('teams/<int:team_id>/members/', views.get_team_members, name='get_team_members'),
    path('roles/', views.role_permissions, name='role_permissions'),
    path('roles/<int:role_id>/permissions/', views.get_role_permissions, name='get_role_permissions'),
    path('roles/create/', views.create_role, name='create_role'),
    path('roles/<int:role_id>/edit/', views.edit_role, name='edit_role'),
    path('roles/<int:role_id>/delete/', views.delete_role, name='delete_role'),
    path('roles/<int:role_id>/permissions/assign/', views.assign_role_permissions, name='assign_role_permissions'),
    path('roles/<int:role_id>/users/', views.get_role_users, name='get_role_users'),
    path('roles/<int:role_id>/users/assign/', views.assign_user_to_role, name='assign_user_to_role'),
    path('roles/<int:role_id>/users/<int:user_id>/remove/', views.remove_user_from_role, name='remove_user_from_role'),
    path('licenses/', views.license_management, name='license_management'),
    path('licenses/assign/', views.assign_user_license, name='assign_user_license'),
    path('licenses/revoke/', views.revoke_user_license, name='revoke_user_license'),
    path('licenses/create-custom/', views.create_custom_license, name='create_custom_license'),
    path('subscription/', views.subscription_plans, name='subscription_plans'),
    path('logs/', views.system_logs, name='system_logs'),
    path('integrations/', views.integrations, name='integrations'),
    path('integrations/<str:integration_name>/configure/', views.configure_integration, name='configure_integration'),
    path('integrations/<str:integration_name>/test/', views.test_integration, name='test_integration'),
]
