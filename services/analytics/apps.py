from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'services.analytics'
    label = 'services_analytics'
    verbose_name = 'Analytics Service'