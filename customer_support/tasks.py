"""
Celery background tasks for the customer support portal.

Tasks
-----
- send_csat_survey_email: email CSAT request 24 h after a ticket is closed
- monitor_sla_deadlines: find breached SLA deadlines and send alerts every 30 min
- auto_close_resolved_tickets: close tickets that have been resolved for N days
- send_ticket_notification: create an in-app Notification record for ticket events
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone

from core.models import Notification

logger = logging.getLogger(__name__)

_SUPPORT_CFG = lambda key, default=None: getattr(settings, 'CUSTOMER_SUPPORT', {}).get(key, default)  # noqa: E731


# ---------------------------------------------------------------------------
# In-app notifications
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_ticket_notification(self, recipient_id, title, message, ticket_id, ticket_pk, action_url=''):
    """Create a core.Notification record for a ticket event."""
    try:
        Notification.objects.create(
            recipient_id=recipient_id,
            title=title,
            message=message,
            notification_type='info',
            content_type='SupportTicket',
            object_id=str(ticket_pk),
            action_url=action_url or f'/support/portal/tickets/{ticket_id}/',
            action_text='View Ticket',
        )
    except Exception as exc:
        logger.exception('send_ticket_notification failed for ticket %s', ticket_id)
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# CSAT survey
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_csat_survey_email(self, ticket_pk):
    """
    Send a CSAT survey email to the ticket creator 24 h after the ticket closes.
    Called from the ticket_close view / API action via Celery delay.
    """
    from .models import SupportTicket  # local import avoids circular at module level

    try:
        ticket = SupportTicket.objects.select_related('created_by').get(pk=ticket_pk)
    except SupportTicket.DoesNotExist:
        return

    if not _SUPPORT_CFG('EMAIL_NOTIFICATIONS_ENABLED', True):
        return

    recipient_email = ticket.created_by.email
    if not recipient_email:
        return

    site_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')
    close_url = f"{site_url}/support/portal/tickets/{ticket.ticket_id}/"

    try:
        send_mail(
            subject=f'How did we do? – {ticket.ticket_id}',
            message=(
                    f"Hi {ticket.created_by.get_full_name() or ticket.created_by.username},\n\n"
                    f"Your support request '{ticket.title}' ({ticket.ticket_id}) has been closed.\n\n"
                    f"We'd love to hear how we did. Visit your ticket to leave a satisfaction score (1-5):\n{close_url}\n\n"
                    f"Thank you!\nThe Support Team"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            fail_silently=True,
        )
    except Exception as exc:
        logger.exception('CSAT email failed for ticket %s', ticket.ticket_id)
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# SLA monitoring (runs every 30 min via Celery Beat)
# ---------------------------------------------------------------------------

@shared_task
def monitor_sla_deadlines():
    """
    Find tickets with breached SLA deadlines and create Notification records
    for the assigned agent (or all support agents if unassigned).
    """
    from .models import SupportTicket

    now = timezone.now()
    breached = SupportTicket.objects.filter(
        sla_deadline__isnull=False,
        sla_deadline__lt=now,
        is_archived=False,
    ).exclude(status__in=['resolved', 'closed']).select_related('assigned_to', 'organization')

    for ticket in breached:
        recipients = []
        if ticket.assigned_to is not None:
            recipients = [ticket.assigned_to]
        else:
            # Fallback: notify active support operators/admins in the organization.
            user_model = get_user_model()
            recipients = list(
                user_model.objects.filter(
                    mediap_profile__organization=ticket.organization,
                    is_active=True,
                ).filter(
                    Q(is_staff=True)
                    | Q(groups__name='support_admin')
                    | Q(groups__name='support_agent')
                    | Q(groups__name='customer_support')
                ).distinct()
            )

        for recipient in recipients:
            Notification.objects.get_or_create(
                recipient=recipient,
                content_type='SupportTicket',
                object_id=str(ticket.pk),
                title=f'SLA Breached: {ticket.ticket_id}',
                defaults={
                    'message': f'Ticket "{ticket.title}" has breached its SLA deadline.',
                    'notification_type': 'warning',
                    'action_url': f'/support/tickets/{ticket.ticket_id}/',
                    'action_text': 'View Ticket',
                },
            )
    logger.info('SLA monitor: checked %d breached tickets', breached.count())


# ---------------------------------------------------------------------------
# Auto-close resolved tickets (runs daily via Celery Beat)
# ---------------------------------------------------------------------------

@shared_task
def auto_close_resolved_tickets():
    """
    Close tickets that have been in 'resolved' status for more than
    CUSTOMER_SUPPORT['AUTO_CLOSE_AFTER_DAYS'] days without further activity.
    """
    from .models import SupportTicket

    auto_close_days = _SUPPORT_CFG('AUTO_CLOSE_AFTER_DAYS', 14)
    cutoff = timezone.now() - timedelta(days=auto_close_days)

    resolved_qs = SupportTicket.objects.filter(
        status='resolved',
        resolved_at__lt=cutoff,
        is_archived=False,
    )
    count = 0
    for ticket in resolved_qs.iterator():
        ticket.status = 'closed'
        ticket.save(update_fields=['status', 'updated_at', 'resolved_at', 'closed_at'])
        count += 1
    logger.info('Auto-close: closed %d resolved tickets older than %d days', count, auto_close_days)
