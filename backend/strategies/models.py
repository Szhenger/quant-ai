import uuid

from django.core.validators import MinValueValidator
from django.db import models

from core.models import Workspace
from marketdata import INDICATOR_SPECS, OPERATORS

INDICATOR_CHOICES = [(k, v["label"]) for k, v in INDICATOR_SPECS.items()]
OPERATOR_CHOICES = [(k, v) for k, v in OPERATORS.items()]


class Strategy(models.Model):
    """A user-defined market-monitoring rule.

    "When <indicator> on <ticker> is <operator> <threshold>, (optionally) ask the
    AI whether it's a real signal, and if so alert me."
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="strategies")

    name = models.CharField(max_length=200)
    ticker = models.CharField(max_length=16)

    # Quantitative condition.
    # Simple mode uses the flat (indicator, params, operator, threshold) columns.
    # Composite mode stores a full AND/OR condition tree in ``condition`` (the
    # authoritative representation when present); the flat columns are then kept
    # populated with a representative leaf for display and backwards compatibility.
    indicator = models.CharField(max_length=20, choices=INDICATOR_CHOICES)
    params = models.JSONField(default=dict, blank=True)  # e.g. {"window": 20}
    operator = models.CharField(max_length=12, choices=OPERATOR_CHOICES)
    threshold = models.FloatField()
    condition = models.JSONField(null=True, blank=True, default=None)

    # AI contextualisation
    ai_enabled = models.BooleanField(default=True)
    ai_prompt = models.TextField(blank=True, default="")

    # Delivery channels
    notify_in_app = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=False)
    webhook_url = models.URLField(max_length=1000, blank=True, default="")

    # Scheduling / lifecycle
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    # Floored at 1: a 0-minute poll would re-evaluate every sweep, and a 0-minute
    # cooldown would remove the only anti-spam guard (an alert every evaluation).
    poll_interval_minutes = models.PositiveIntegerField(
        default=15, validators=[MinValueValidator(1)]
    )
    cooldown_minutes = models.PositiveIntegerField(
        default=60, validators=[MinValueValidator(1)]
    )

    last_evaluated_at = models.DateTimeField(null=True, blank=True)
    last_triggered_at = models.DateTimeField(null=True, blank=True)
    last_metric_value = models.FloatField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "last_evaluated_at"])]

    def save(self, *args, **kwargs):
        self.ticker = self.ticker.upper().strip()
        super().save(*args, **kwargs)

    def condition_tree(self) -> dict:
        """The strategy's firing condition as a validated tree.

        Composite strategies store the tree in ``condition``; simple strategies
        synthesise a one-leaf tree from their flat columns — so evaluation and
        replay both take a single code path regardless of how it was authored.
        """
        from marketdata import simple_condition, validate_condition_tree

        tree = self.condition or simple_condition(
            self.indicator, self.operator, self.threshold, self.params
        )
        return validate_condition_tree(tree)

    def __str__(self):
        return f"{self.name} ({self.ticker})"


class Alert(models.Model):
    """A fired alert — one record per time a strategy's conditions were met."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="alerts")
    strategy = models.ForeignKey(
        Strategy, on_delete=models.SET_NULL, null=True, related_name="alerts"
    )

    ticker = models.CharField(max_length=16)
    indicator = models.CharField(max_length=20)
    operator = models.CharField(max_length=12)
    threshold = models.FloatField()
    metric_value = models.FloatField()

    ai_used = models.BooleanField(default=False)
    ai_rationale = models.TextField(blank=True, default="")
    message = models.TextField(blank=True, default="")

    # True when the prices (and/or headlines) this alert was computed from were
    # synthetic fallback data rather than real market data. Surfaced so the user
    # always knows how much to trust an alert.
    data_synthetic = models.BooleanField(default=False)

    # The evaluated condition tree that fired this alert: every leaf carries the
    # concrete operand values that produced it. Written inside the same
    # transaction as the alert — a reproducible audit row, not a side effect.
    condition_detail = models.JSONField(default=dict, blank=True)

    delivery = models.JSONField(default=dict, blank=True)  # {channel: {ok, detail}}
    is_read = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "is_read"]),
            # Backs cursor pagination: each page is a range scan on
            # (workspace, created_at DESC) instead of an offset scan.
            models.Index(fields=["workspace", "-created_at"]),
        ]

    def __str__(self):
        return f"Alert {self.ticker} {self.indicator} @ {self.created_at:%Y-%m-%d %H:%M}"
