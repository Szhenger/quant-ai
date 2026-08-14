import math

from rest_framework import serializers

from identity.validators import ensure_public_webhook_url, normalize_ticker
from feeder import (
    INDICATOR_SPECS,
    OPERATORS,
    describe_tree,
    validate_params,
    validate_condition_tree,
    representative_fields,
)
from .models import Strategy, Alert

# Upper bound on the free-text prompt forwarded to the AI on every evaluation.
# Unbounded, it is a cost-amplification vector: N strategies x 1-minute polls
# x an arbitrarily large prompt, all billed against the operator's API key.
AI_PROMPT_MAX_LENGTH = 2000


class StrategySerializer(serializers.ModelSerializer):
    # Composite mode: an AND/OR condition tree. When present it is authoritative
    # and the flat indicator/operator/threshold columns are derived from it.
    condition = serializers.JSONField(required=False, allow_null=True)
    ai_prompt = serializers.CharField(
        required=False, allow_blank=True, max_length=AI_PROMPT_MAX_LENGTH
    )
    # The strategy's real firing rule as one human-readable line — for composite
    # strategies the flat columns only show a representative leaf, which is not
    # what the user authored.
    condition_summary = serializers.SerializerMethodField()

    class Meta:
        model = Strategy
        fields = (
            "id", "name", "ticker",
            "indicator", "params", "operator", "threshold", "condition",
            "condition_summary",
            "ai_enabled", "ai_prompt",
            "notify_in_app", "notify_email", "webhook_url", "webhook_secret",
            "status", "poll_interval_minutes", "cooldown_minutes",
            "consecutive_failures",
            "last_evaluated_at", "last_triggered_at", "last_metric_value", "last_error",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "webhook_secret", "condition_summary", "consecutive_failures",
            "last_evaluated_at", "last_triggered_at", "last_metric_value",
            "last_error", "created_at", "updated_at",
        )
        # In composite mode the client sends only `condition`; the flat columns are
        # filled server-side, so they must not be required at the field level.
        extra_kwargs = {
            "indicator": {"required": False},
            "operator": {"required": False},
            "threshold": {"required": False},
        }

    def get_condition_summary(self, obj) -> str:
        try:
            return describe_tree(obj.condition_tree())
        except Exception:  # noqa: BLE001 — display-only; never fail a list over it
            return ""

    def validate_ticker(self, value):
        try:
            return normalize_ticker(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))

    def validate_webhook_url(self, value):
        if value:
            try:
                ensure_public_webhook_url(value)
            except ValueError as exc:
                raise serializers.ValidationError(str(exc))
        return value

    def validate_threshold(self, value):
        # DRF's FloatField accepts "NaN"/"Infinity": NaN never compares true (a
        # rule that silently never fires) and both break strict-JSON payloads.
        if value is not None and not math.isfinite(value):
            raise serializers.ValidationError("Threshold must be a finite number.")
        return value

    def validate_indicator(self, value):
        if value not in INDICATOR_SPECS:
            raise serializers.ValidationError(f"Unknown indicator: {value}")
        return value

    def validate_operator(self, value):
        if value not in OPERATORS:
            raise serializers.ValidationError(f"Unknown operator: {value}")
        return value

    def update(self, instance, validated_data):
        # Reactivating a strategy re-arms its circuit breaker.
        if (validated_data.get("status") == Strategy.Status.ACTIVE
                and instance.status != Strategy.Status.ACTIVE):
            validated_data["consecutive_failures"] = 0
        return super().update(instance, validated_data)

    def validate(self, attrs):
        condition = attrs.get("condition", getattr(self.instance, "condition", None))
        if condition:
            return self._validate_composite(attrs, condition)
        return self._validate_simple(attrs)

    def _validate_composite(self, attrs, condition):
        try:
            tree = validate_condition_tree(condition)
        except ValueError as exc:
            raise serializers.ValidationError({"condition": str(exc)})
        attrs["condition"] = tree
        # Keep the flat columns populated with a representative leaf so legacy
        # readers (the alert row, list views) stay coherent.
        rep = representative_fields(tree)
        attrs["indicator"] = rep["indicator"]
        attrs["params"] = rep["params"]
        attrs["operator"] = rep["operator"]
        attrs["threshold"] = rep["threshold"]
        return attrs

    def _validate_simple(self, attrs):
        indicator = attrs.get("indicator") or getattr(self.instance, "indicator", None)
        if not indicator:
            raise serializers.ValidationError({"indicator": "This field is required."})
        if attrs.get("operator") is None and getattr(self.instance, "operator", None) is None:
            raise serializers.ValidationError({"operator": "This field is required."})
        if attrs.get("threshold") is None and getattr(self.instance, "threshold", None) is None:
            raise serializers.ValidationError({"threshold": "This field is required."})
        params = attrs.get("params", getattr(self.instance, "params", None))
        try:
            attrs["params"] = validate_params(indicator, params)
        except ValueError as exc:
            raise serializers.ValidationError({"params": str(exc)})
        return attrs


class AlertSerializer(serializers.ModelSerializer):
    strategy_name = serializers.CharField(source="strategy.name", default=None, read_only=True)

    class Meta:
        model = Alert
        fields = (
            "id", "strategy", "strategy_name", "ticker", "indicator", "operator",
            "threshold", "metric_value", "ai_used", "ai_rationale", "ai_confidence",
            "message", "condition_detail", "data_synthetic", "delivery", "is_read",
            "created_at",
        )
        read_only_fields = fields
