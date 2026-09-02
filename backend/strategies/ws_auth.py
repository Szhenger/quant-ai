"""JWT authentication middleware for WebSocket connections.

The browser can't set Authorization headers on a WebSocket, so the access
token rides in the ``Sec-WebSocket-Protocol`` header: the client offers the
subprotocols ``["quantai.v1", "quantai.token.<jwt>"]`` and the consumer
accepts ``quantai.v1``. Unlike a ``?token=`` query parameter, a request
header is not written to proxy/load-balancer access logs, APM traces, or
browser history. (A JWT is unpadded base64url + dots — all valid RFC 6455
subprotocol token characters.)

This middleware resolves the offered token to a user on ``scope['user']``
(AnonymousUser on any failure); the consumer then checks workspace ownership.
"""
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

TOKEN_SUBPROTOCOL_PREFIX = "quantai.token."


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        token = None
        for offered in scope.get("subprotocols") or []:
            if offered.startswith(TOKEN_SUBPROTOCOL_PREFIX):
                token = offered[len(TOKEN_SUBPROTOCOL_PREFIX):]
                break
        scope["user"] = await self._authenticate(token)
        return await super().__call__(scope, receive, send)

    @database_sync_to_async
    def _authenticate(self, token):
        if not token:
            return AnonymousUser()
        try:
            from rest_framework_simplejwt.tokens import AccessToken

            access = AccessToken(token)
            # is_active mirrors JWTAuthentication over HTTP: a deactivated
            # account's still-valid access token must not open a socket.
            return get_user_model().objects.get(id=access["user_id"], is_active=True)
        except Exception:  # noqa: BLE001
            return AnonymousUser()
