"""JWT authentication middleware for WebSocket connections.

The browser can't set Authorization headers on a WebSocket, so the access token
is passed as a ``?token=`` query parameter. This resolves it to a user and puts
it on ``scope['user']`` (AnonymousUser on any failure); the consumer then checks
workspace ownership.
"""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query = parse_qs(scope.get("query_string", b"").decode())
        token = (query.get("token") or [None])[0]
        scope["user"] = await self._authenticate(token)
        return await super().__call__(scope, receive, send)

    @database_sync_to_async
    def _authenticate(self, token):
        if not token:
            return AnonymousUser()
        try:
            from rest_framework_simplejwt.tokens import AccessToken

            access = AccessToken(token)
            # is_active mirrors DRF's JWTAuthentication on the HTTP path: a
            # deactivated account must not keep a live alert stream.
            return get_user_model().objects.get(id=access["user_id"], is_active=True)
        except Exception:  # noqa: BLE001
            return AnonymousUser()
