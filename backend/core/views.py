from rest_framework import generics, permissions, viewsets

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
        serializer.save(workspace=workspace)
