"""WebSocket consumer that streams alerts to an authenticated, workspace-scoped client."""
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from core.models import Workspace


class AlertConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        self.workspace_id = self.scope["url_route"]["kwargs"]["workspace_id"]

        if user is None or not user.is_authenticated:
            await self.close(code=4001)  # unauthenticated
            return
        if not await self._owns(user, self.workspace_id):
            await self.close(code=4003)  # not your workspace
            return

        self.group = f"ws_{self.workspace_id}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_json({"type": "connected", "workspace_id": self.workspace_id})

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        """Client heartbeat. Browsers don't surface a half-open TCP connection
        (proxy died, laptop slept) — the socket looks open but delivers
        nothing. The client pings periodically; a missed pong tells it to
        tear down and reconnect. ``t`` is echoed for client-side RTT."""
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong", "t": content.get("t")})

    async def alert_message(self, event):
        """Handler for {'type': 'alert.message', 'data': ...} group sends."""
        await self.send_json({"type": "alert", "alert": event["data"]})

    @database_sync_to_async
    def _owns(self, user, workspace_id):
        # A malformed (non-UUID) workspace_id in the URL raises ValidationError on
        # the query; treat that as "not owned" and close cleanly rather than error.
        from django.core.exceptions import ValidationError

        try:
            return Workspace.objects.filter(id=workspace_id, owner=user).exists()
        except (ValidationError, ValueError):
            return False
