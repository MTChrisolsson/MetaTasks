"""
Django Channels WebSocket consumers for the customer support portal.

Each authenticated user is joined to their organization's ticket group
(`ticket_org_{org_id}`), receiving real-time events for ticket creation,
status changes, new comments, and closures.
"""

import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

logger = logging.getLogger(__name__)


class SupportTicketConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for real-time ticket events.

    Clients connect to /ws/support/tickets/ and are automatically enrolled
    in their organisation's channel group.

    Outbound message shape:
        {
            "type": "ticket.created" | "ticket.updated" | "ticket.comment" | "ticket.closed",
            "ticket_id": "TKT-00001",
            "title": "...",
            "status": "open",
            "priority": "high",
            "assigned_to": "username" | null,
            "comment_author": "username",   # only for ticket.comment
            "comment_preview": "...",        # only for ticket.comment (first 120 chars)
            "timestamp": "2026-01-01T00:00:00Z",
        }
    """

    async def connect(self):
        user = self.scope['user']
        if not user.is_authenticated:
            await self.close(code=4001)
            return

        org_id = await self._get_org_id(user)
        if org_id is None:
            await self.close(code=4003)
            return

        self.group_name = f'ticket_org_{org_id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.debug('WS connected: user=%s group=%s', user.username, self.group_name)

    async def disconnect(self, code):
        group = getattr(self, 'group_name', None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    # ------------------------------------------------------------------ #
    # Receive (clients do not send messages in this implementation)
    # ------------------------------------------------------------------ #
    async def receive_json(self, content, **kwargs):
        pass  # read-only stream; ignore any client messages

    # ------------------------------------------------------------------ #
    # Group message handlers – called when channel_layer.group_send fires
    # ------------------------------------------------------------------ #
    async def ticket_created(self, event):
        await self.send_json({**event, 'type': 'ticket.created'})

    async def ticket_updated(self, event):
        await self.send_json({**event, 'type': 'ticket.updated'})

    async def ticket_comment(self, event):
        await self.send_json({**event, 'type': 'ticket.comment'})

    async def ticket_closed(self, event):
        await self.send_json({**event, 'type': 'ticket.closed'})

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @database_sync_to_async
    def _get_org_id(self, user):
        profile = getattr(user, 'mediap_profile', None)
        if profile and profile.organization_id:
            return profile.organization_id
        return None
