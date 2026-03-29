from django.urls import path

from . import views

app_name = 'customer_support'

urlpatterns = [
    path('', views.portal_dashboard, name='dashboard'),
    path('licensing/', views.support_licensing_dashboard, name='support_licensing_dashboard'),
    path('licensing/<int:org_id>/', views.support_licensing_organization_detail, name='support_licensing_organization_detail'),
    path('tickets/dashboard/', views.ticket_dashboard, name='ticket_dashboard'),
    path('tickets/', views.ticket_list, name='ticket_list'),
    path('tickets/create/', views.ticket_create, name='ticket_create'),
    path('tickets/<str:ticket_id>/', views.ticket_detail, name='ticket_detail'),
    path('tickets/<str:ticket_id>/update/', views.ticket_update, name='ticket_update'),
    path('tickets/<str:ticket_id>/comment/', views.ticket_add_comment, name='ticket_add_comment'),
    path('tickets/<str:ticket_id>/close/', views.ticket_close, name='ticket_close'),
    path('tickets/<str:ticket_id>/merge/', views.ticket_merge, name='ticket_merge'),
    path('tickets/<str:ticket_id>/export/', views.ticket_export, name='ticket_export'),
    # Analytics
    path('analytics/', views.support_analytics, name='analytics'),
    path('analytics/team/', views.team_performance, name='team_performance'),
    path('analytics/trends/', views.ticket_trends, name='ticket_trends'),
    # Accounts
    path('accounts/', views.account_management, name='account_management'),
    path('accounts/<int:user_id>/', views.account_detail, name='account_detail'),
    path('accounts/<int:user_id>/toggle-status/', views.toggle_account_status, name='toggle_account_status'),
    # Knowledge Base
    path('kb/', views.kb_list, name='kb_list'),
    path('kb/create/', views.kb_article_create, name='kb_article_create'),
    path('kb/<slug:slug>/', views.kb_article_detail, name='kb_article_detail'),
    path('kb/<slug:slug>/edit/', views.kb_article_edit, name='kb_article_edit'),
    path('kb/<slug:slug>/helpful/', views.kb_article_helpful, name='kb_article_helpful'),
    # Customer portal
    path('portal/', views.customer_portal_home, name='portal_home'),
    path('portal/tickets/', views.customer_my_tickets, name='customer_my_tickets'),
    path('portal/tickets/new/', views.customer_ticket_create, name='customer_ticket_create'),
    path('portal/tickets/<str:ticket_id>/', views.customer_ticket_detail, name='customer_ticket_detail'),
]
