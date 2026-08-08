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


class WatchedTicker(models.Model):
    """A market the user wants to follow. Drives the market-analysis dashboard
    and provides quick-pick tickers for strategy creation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="watchlist"
    )
    ticker = models.CharField(max_length=16)
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("workspace", "ticker")
        ordering = ["ticker"]

    def save(self, *args, **kwargs):
        self.ticker = self.ticker.upper().strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.ticker} @ {self.workspace_id}"
