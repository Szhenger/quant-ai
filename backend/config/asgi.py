import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.asgi import get_asgi_application

# Initialise Django before importing anything that touches the app registry.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import OriginValidator  # noqa: E402
from django.conf import settings  # noqa: E402
from engine.ws_auth import JWTAuthMiddleware  # noqa: E402
from engine.routing import websocket_urlpatterns  # noqa: E402

# Origin check first: browsers on foreign origins are refused before any token
# is even looked at (auth is token-based, so classic CSWSH doesn't apply — this
# is defence in depth). The console is served from a separate origin, so the
# allowlist is the CORS one, not ALLOWED_HOSTS; the API's own hosts are added
# for same-origin tooling (browsable docs, admin).
_ws_allowed_origins = list(settings.CORS_ALLOWED_ORIGINS) + [
    host for host in settings.ALLOWED_HOSTS if host and host != "*"
]

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": OriginValidator(
            JWTAuthMiddleware(URLRouter(websocket_urlpatterns)),
            _ws_allowed_origins,
        ),
    }
)
