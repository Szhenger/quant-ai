"""WebSocket consumer that streams alerts to an authenticated, workspace-scoped client."""
import uuid

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from core.models import Workspace


class AlertConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        raw_id = self.scope["url_route"]["kwargs"]["workspace_id"]

        if user is None or not user.is_authenticated:
            await self.close(code=4001)  # unauthenticated
            return
        try:
            # Canonical lowercase-hyphenated form: the group name must match
            # delivery's f"ws_{alert.workspace_id}" exactly, however the URL
            # spelled the id (uppercase hex would pass the ownership check but
            # join a group that never receives messages).
            self.workspace_id = str(uuid.UUID(raw_id))
        except ValueError:
            await self.close(code=4003)  # malformed id is nobody's workspace
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
        # Heartbeat: the client pings every ~25s and declares the connection
        # half-open (then reconnects) if the pong doesn't come back.
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong", "t": content.get("t")})

    async def alert_message(self, event):
        """Handler for {'type': 'alert.message', 'data': ...} group sends."""
        await self.send_json({"type": "alert", "alert": event["data"]})

    @database_sync_to_async
    def _owns(self, user, workspace_id):
        # workspace_id is already a validated canonical UUID string here.
        return Workspace.objects.filter(id=workspace_id, owner=user).exists()
