from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, permissions, viewsets
from rest_framework import serializers as rf_serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .limits import account_limits
from .models import Workspace
from .serializers import RegisterSerializer, WorkspaceSerializer
from .workspaces import resolve_active_workspace


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class LogoutView(APIView):
    """Blacklist the submitted refresh token, ending the session server-side.

    Without this, "log out" only clears the client's storage while the refresh
    token stays valid for its full lifetime. Idempotent: an already-blacklisted,
    expired or malformed token still returns success — the caller's goal (that
    token no longer works) is met either way.

    AllowAny is deliberate: possession of a validly-signed refresh token IS the
    credential, and the only effect is revoking that same token. Requiring an
    access token would also break the common case — logging out with an access
    token that already expired.
    """

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=inline_serializer(name="LogoutRequest",
                                  fields={"refresh": rf_serializers.CharField()}),
        responses={205: None},
    )
    def post(self, request):
        from rest_framework_simplejwt.exceptions import TokenError
        from rest_framework_simplejwt.tokens import RefreshToken

        raw = request.data.get("refresh")
        if not raw:
            raise ValidationError({"refresh": "This field is required."})
        try:
            RefreshToken(raw).blacklist()
        except TokenError:
            pass
        return Response(status=205)


class WorkspaceViewSet(viewsets.ModelViewSet):
    """Owner-scoped CRUD for workspaces."""

    serializer_class = WorkspaceSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # schema introspection
            return Workspace.objects.none()
        return Workspace.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class LimitsView(APIView):
    """The account guards this workspace runs under: the strategy cap and how
    much of it is used, the daily AI-call budget and how much is spent. The
    console reads it next to every deploy button."""

    @extend_schema(responses=OpenApiTypes.OBJECT, operation_id="account_limits")
    def get(self, request):
        workspace = resolve_active_workspace(request)
        return Response(account_limits(workspace, request.user))
