from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api_views

app_name = 'customer_support_api'

router = DefaultRouter()
router.register('tickets', api_views.SupportTicketViewSet, basename='support-tickets')
router.register('tags', api_views.SupportTagViewSet, basename='support-tags')
router.register('templates', api_views.SupportTemplateViewSet, basename='support-templates')
router.register('relationships', api_views.TicketRelationshipViewSet, basename='support-relationships')
router.register('audit-logs', api_views.SupportTicketAuditLogViewSet, basename='support-audit-logs')
router.register('kb/articles', api_views.KBArticleViewSet, basename='kb-articles')
router.register('kb/categories', api_views.KBCategoryViewSet, basename='kb-categories')

urlpatterns = [
    path('', include(router.urls)),
    path('analytics/dashboard/', api_views.SupportAnalyticsDashboardAPIView.as_view(), name='analytics-dashboard'),
    path('analytics/sla-performance/', api_views.SupportAnalyticsSLAAPIView.as_view(), name='analytics-sla'),
    path('analytics/team-metrics/', api_views.SupportAnalyticsTeamAPIView.as_view(), name='analytics-team'),
    path('analytics/csv-export/', api_views.SupportAnalyticsCSVExportAPIView.as_view(), name='analytics-csv-export'),
]
