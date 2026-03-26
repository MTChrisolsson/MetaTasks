from django import template
from django.urls import NoReverseMatch, reverse

from services.analytics.models import AnalyticsTool

register = template.Library()


UNIVERSAL_ANALYTICS_TOOLS = [
    {
        'name': 'Data Health Monitor',
        'description': 'Monitor feed freshness and data quality checks.',
        'icon': 'fas fa-heart-pulse',
        'view_name': 'analytics:data_health_monitor',
    },
    {
        'name': 'Scheduled Report Builder',
        'description': 'Create recurring report templates and delivery schedules.',
        'icon': 'fas fa-calendar-check',
        'view_name': 'analytics:scheduled_report_builder',
    },
    {
        'name': 'KPI Builder',
        'description': 'Define custom KPIs, targets, and trend tracking.',
        'icon': 'fas fa-chart-column',
        'view_name': 'analytics:kpi_builder',
    },
    {
        'name': 'Alert Center',
        'description': 'Track threshold and anomaly alerts with assignment and status.',
        'icon': 'fas fa-bell',
        'view_name': 'analytics:alert_center',
    },
]

UNIVERSAL_ANALYTICS_TOOL_SLUGS = {
    'data-health-monitor',
    'scheduled-report-builder',
    'kpi-builder',
    'alert-center',
}


@register.simple_tag
def organization_analytics_tools(profile):
    """Return active analytics tools for the profile's organization."""
    if not profile or not getattr(profile, 'organization', None):
        return []

    tools = (
        AnalyticsTool.objects.filter(organization=profile.organization, is_active=True)
        .order_by('sort_order', 'name')
    )

    resolved_tools = []
    for tool in tools:
        if tool.slug in UNIVERSAL_ANALYTICS_TOOL_SLUGS:
            # Universal tools are shown in a dedicated global Tools nav section.
            continue

        href = ''
        if tool.action_type == 'internal_url':
            href = tool.target_path
        elif tool.action_type == 'named_view' and tool.target_view_name:
            try:
                href = reverse(tool.target_view_name)
            except NoReverseMatch:
                href = ''

        if href:
            resolved_tools.append(
                {
                    'id': tool.id,
                    'name': tool.name,
                    'description': tool.description,
                    'icon': tool.icon or 'fas fa-tools',
                    'href': href,
                    'open_in_new_tab': tool.open_in_new_tab,
                }
            )

    return resolved_tools


@register.simple_tag
def universal_analytics_tools():
    """Return globally available analytics tools for licensed users."""
    items = []
    for tool in UNIVERSAL_ANALYTICS_TOOLS:
        try:
            href = reverse(tool['view_name'])
        except NoReverseMatch:
            href = ''
        if not href:
            continue

        items.append(
            {
                'name': tool['name'],
                'description': tool['description'],
                'icon': tool['icon'],
                'href': href,
            }
        )
    return items
