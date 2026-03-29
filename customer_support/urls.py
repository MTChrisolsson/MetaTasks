from django.urls import path

from . import views

app_name = 'customer_support'

urlpatterns = [
    path('', views.portal_dashboard, name='dashboard'),
    path('accounts/', views.account_management, name='account_management'),
    path('accounts/<int:user_id>/', views.account_detail, name='account_detail'),
    path('accounts/<int:user_id>/toggle-status/', views.toggle_account_status, name='toggle_account_status'),
]
