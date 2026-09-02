import uuid

from django.conf import settings
from django.db import models


class Workspace(models.Model):
    """A tenant boundary. A user owns one or more workspaces; all strategies,
    watchlists and alerts belong to exactly one workspace."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspaces"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name
