from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'analytics'

router = DefaultRouter()
router.register(r'jobs', views.AnalyticsViewSet, basename='analytics-jobs')

urlpatterns = [
    path('', views.index, name='index'),
    path('data-health-monitor/', views.data_health_monitor, name='data_health_monitor'),
    path('scheduled-reports/', views.scheduled_report_builder, name='scheduled_report_builder'),
    path('scheduled-reports/export/', views.scheduled_report_export, name='scheduled_report_export'),
    path('kpi-builder/', views.kpi_builder, name='kpi_builder'),
    path('alert-center/', views.alert_center, name='alert_center'),
    path('blocket-listings/', views.blocket_listings, name='blocket_listings'),
    path('upload/', views.upload, name='upload'),
    path('statistik-lite/', views.statistik_lite, name='statistik_lite'),
    path('jobs/', views.jobs_list, name='jobs_list'),
    path('lite-jobs/', views.lite_jobs_list, name='lite_jobs_list'),
    path('lite-jobs/<int:job_id>/', views.lite_job_detail, name='lite_job_detail'),
    path('jobs/<int:job_id>/', views.job_detail, name='job_detail'),
    path('jobs/<int:job_id>/citk-wayke/', views.job_citk_wayke_compare, name='job_citk_wayke_compare'),
    path('jobs/<int:job_id>/export/excel/', views.export_excel, name='export_excel'),
    path('api/valuations/', views.VehicleValuationAPIView.as_view(), name='api_valuations'),
    path('api/', include(router.urls)),
]