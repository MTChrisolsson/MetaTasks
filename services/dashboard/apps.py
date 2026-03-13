from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "services.dashboard"
    label = "services_dashboard"
    verbose_name = "Service Dashboard"