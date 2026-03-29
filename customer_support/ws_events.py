"""
Async channel-layer helpers for broadcasting ticket events.

Usage (from synchronous Django views):
    from asgiref.sync import async_to_sync
    from customer_support.ws_events import notify_ticket_event

    async_to_sync(notify_ticket_event)(ticket, 'ticket.created')
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

logger = logging.getLogger(__name__)


def _build_event(ticket, event_type, extra=None):
    payload = {
        'type': event_type.replace('.', '_'),  # channels needs underscores for handler method names
        'ticket_id': ticket.ticket_id,
        'title': ticket.title,
        'status': ticket.status,
        'priority': ticket.priority,
        'assigned_to': ticket.assigned_to.username if ticket.assigned_to else None,
        'timestamp': timezone.now().isoformat(),
    }
    if extra:
        payload.update(extra)
    return payload


def broadcast_ticket_event(ticket, event_type, extra=None):
    """
    Synchronous wrapper – safe to call from regular Django views/tasks.
    Silently skips if channel layer is not configured.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    group_name = f'ticket_org_{ticket.organization_id}'
    event = _build_event(ticket, event_type, extra)
    try:
        async_to_sync(channel_layer.group_send)(group_name, event)
    except Exception:  # noqa: BLE001
        logger.warning('Failed to broadcast WebSocket event %s for ticket %s', event_type, ticket.ticket_id, exc_info=True)
