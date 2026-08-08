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

    async def alert_message(self, event):
        """Handler for {'type': 'alert.message', 'data': ...} group sends."""
        await self.send_json({"type": "alert", "alert": event["data"]})

    @database_sync_to_async
    def _owns(self, user, workspace_id):
        return Workspace.objects.filter(id=workspace_id, owner=user).exists()
