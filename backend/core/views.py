from django.core.cache import cache
from django.db import IntegrityError, connections
from rest_framework import generics, permissions, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Workspace, WatchedTicker
from .serializers import (
    RegisterSerializer,
    WorkspaceSerializer,
    WatchedTickerSerializer,
)
from .workspaces import resolve_active_workspace


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class HealthView(APIView):
    """Liveness/readiness probe: verifies the database and the shared cache.

    Unauthenticated and unthrottled — load balancers and uptime monitors hit it
    frequently and must never be rate-limited or asked for credentials.
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

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


class WorkspaceViewSet(viewsets.ModelViewSet):
    """Owner-scoped CRUD for workspaces."""

    serializer_class = WorkspaceSerializer

    def get_queryset(self):
        return Workspace.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class WatchedTickerViewSet(viewsets.ModelViewSet):
    """The active workspace's watchlist (markets the user follows)."""

    serializer_class = WatchedTickerSerializer

    def get_queryset(self):
        workspace = resolve_active_workspace(self.request)
        return WatchedTicker.objects.filter(workspace=workspace)

    def perform_create(self, serializer):
        workspace = resolve_active_workspace(self.request)
        try:
            serializer.save(workspace=workspace)
        except IntegrityError:
            # Backstop for the serializer's exists() check losing a race.
            raise ValidationError({"ticker": "This ticker is already on the watchlist."})
