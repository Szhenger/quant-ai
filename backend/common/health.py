"""The liveness/readiness probe (``/healthz/``)."""
from django.core.cache import cache
from django.db import connections
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Liveness/readiness probe: verifies the database and the shared cache.

    Unauthenticated and unthrottled — load balancers and uptime monitors hit it
    frequently and must never be rate-limited or asked for credentials.
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    @extend_schema(responses={200: OpenApiTypes.OBJECT, 503: OpenApiTypes.OBJECT},
                   operation_id="healthz")
    def get(self, request):
        checks = {}
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT 1")
            checks["database"] = True
        except Exception:  # noqa: BLE001
            checks["database"] = False
        try:
            cache.set("quantai:healthz", "1", 5)
            checks["cache"] = cache.get("quantai:healthz") == "1"
        except Exception:  # noqa: BLE001
            checks["cache"] = False
        ok = all(checks.values())
        return Response({"status": "ok" if ok else "degraded", **checks},
                        status=200 if ok else 503)
