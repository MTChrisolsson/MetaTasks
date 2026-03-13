"""
URL configuration for mediap project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('admin/custom/', include('admin.urls')),  # Custom admin views
    path('api/', include('api.urls')),
    path('dashboard/', include(('core.dashboard_urls', 'dashboard'), namespace='dashboard')),  # Dashboard URLs
    path('', include('homepage.urls')),
    path('accounts/', include('accounts.urls')),
    path('core/', include('core.urls')),
    # Services URLs
    # CFlows Service
    path('services/cflows/', include(('services.cflows.urls', 'cflows'), namespace='cflows')),
    # Scheduling service
    path('services/scheduling/', include('services.scheduling.urls')),
    # Staff panel for service management
    path('services/staff-panel/', include('services.staff_panel.urls')),
    # Analytics service
    path('services/analytics/', include(('services.analytics.urls', 'analytics'), namespace='analytics')),
    path('licensing/', include('licensing.urls')),
    # Services dashboard
    path('services/dashboard/', include(('services.dashboard.urls', 'service_dashboard'), namespace='service_dashboard')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
