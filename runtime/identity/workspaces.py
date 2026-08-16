"""Shared helper: resolve the active workspace from the request.

The frontend injects the active workspace via the ``X-Workspace-ID`` header.
This helper validates that the workspace exists *and* is owned by the
authenticated user, giving us tenant isolation at the application layer.
"""
from django.core.exceptions import ValidationError
from rest_framework.exceptions import NotFound, PermissionDenied

from .models import Workspace

WORKSPACE_HEADER = "HTTP_X_WORKSPACE_ID"


def resolve_active_workspace(request) -> Workspace:
    workspace_id = request.META.get(WORKSPACE_HEADER)
    if not workspace_id:
        raise PermissionDenied("Missing X-Workspace-ID header.")
    try:
        return Workspace.objects.get(id=workspace_id, owner=request.user)
    except (Workspace.DoesNotExist, ValidationError, ValueError):
        raise NotFound("Workspace not found or not owned by the current user.") from None
