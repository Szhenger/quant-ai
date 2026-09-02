"""The watchlist and each watched ticker's compiled stock page.

These tables were born in the ``core`` app (today's ``identity``); ``db_table``
pins the historical names so the move is state-only — see
``identity/migrations/0003`` and ``watchlist/migrations/0001``.
"""
import uuid

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

from identity.models import Workspace


def _default_refresh_hours() -> int:
    return int(settings.STOCKPAGE_REFRESH_INTERVAL_HOURS)


def _default_recompute_hours() -> int:
    return int(settings.STOCKPAGE_RECOMPUTE_INTERVAL_HOURS)


class WatchedTicker(models.Model):
    """A market the user wants to follow. Drives the market-analysis dashboard
    and provides quick-pick tickers for strategy creation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="watchlist"
    )
    ticker = models.CharField(max_length=16)
    note = models.CharField(max_length=255, blank=True, default="")
    # n: how often this ticker's qualitative/weekly view refreshes (hours).
    refresh_interval_hours = models.PositiveIntegerField(
        default=_default_refresh_hours,
        validators=[MinValueValidator(1), MaxValueValidator(24 * 30)],
    )
    # m: how often the macro quantitative measure is recomputed (hours). Each
    # recompute retains a compressed snapshot of the previous measure.
    recompute_interval_hours = models.PositiveIntegerField(
        default=_default_recompute_hours,
        validators=[MinValueValidator(1), MaxValueValidator(24 * 90)],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_watchedticker"  # historical name (see module docstring)
        unique_together = ("workspace", "ticker")
        ordering = ["ticker"]

    def save(self, *args, **kwargs):
        self.ticker = self.ticker.upper().strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.ticker} @ {self.workspace_id}"


class StockPage(models.Model):
    """The compiled financial page for a watched ticker.

    Two measures, each stored in both a detailed and a summarised form so the
    client can "view in full detail and summarized too":
      * quantitative — the standard indicators over a macro window (recomputed
        every ``recompute_interval_hours``);
      * qualitative  — this week's news plus a Claude summary (refreshed every
        ``refresh_interval_hours``).
    Persisted (not just cached) so the page survives restarts and provides the
    baseline the compressed snapshots are taken against.
    """

    watched_ticker = models.OneToOneField(
        WatchedTicker, on_delete=models.CASCADE, related_name="page"
    )
    quantitative = models.JSONField(default=dict, blank=True)          # detailed
    quantitative_summary = models.JSONField(default=dict, blank=True)  # summarised
    qualitative = models.JSONField(default=dict, blank=True)           # detailed
    qualitative_summary = models.JSONField(default=dict, blank=True)   # summarised
    data_synthetic = models.BooleanField(default=False)
    # Last time each measure was (re)computed — drive the n/m cadences.
    refreshed_at = models.DateTimeField(null=True, blank=True)    # qualitative (n)
    recomputed_at = models.DateTimeField(null=True, blank=True)   # quantitative (m)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_stockpage"  # historical name (see module docstring)

    def __str__(self):
        return f"page:{self.watched_ticker.ticker}"


class QuantSnapshot(models.Model):
    """A gzip-compressed snapshot of a prior quantitative measure.

    Taken just before each macro recompute so the macroscale trend stays
    continuous across recomputes. Stored compressed because these accrue per
    ticker over months; a bounded number are retained (settings
    ``STOCKPAGE_SNAPSHOT_RETENTION``)."""

    watched_ticker = models.ForeignKey(
        WatchedTicker, on_delete=models.CASCADE, related_name="snapshots"
    )
    taken_at = models.DateTimeField(auto_now_add=True)
    compressed = models.BinaryField()

    class Meta:
        db_table = "core_quantsnapshot"  # historical name (see module docstring)
        ordering = ["-taken_at"]
        indexes = [models.Index(fields=["watched_ticker", "-taken_at"],
                                name="core_quants_watched_02cfad_idx")]

    def __str__(self):
        return f"snapshot:{self.watched_ticker_id}@{self.taken_at:%Y-%m-%d %H:%M}"
