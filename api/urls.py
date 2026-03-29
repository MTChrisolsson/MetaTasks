from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'api'

# DRF Router for API endpoints
router = DefaultRouter()

urlpatterns = [
    path('', include(router.urls)),
    path('auth/', include('rest_framework.urls')),
    path('health/', views.health_check, name='health_check'),
    path('services/', views.services_list, name='services_list'),
    path('support/', include('customer_support.api_urls')),
]