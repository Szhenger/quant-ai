from rest_framework import serializers

from marketdata import INDICATOR_SPECS, OPERATORS, validate_params
from .models import Strategy, Alert


class StrategySerializer(serializers.ModelSerializer):
    class Meta:
        model = Strategy
        fields = (
            "id", "name", "ticker",
            "indicator", "params", "operator", "threshold",
            "ai_enabled", "ai_prompt",
            "notify_in_app", "notify_email", "webhook_url",
            "status", "poll_interval_minutes", "cooldown_minutes",
            "last_evaluated_at", "last_triggered_at", "last_metric_value", "last_error",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "last_evaluated_at", "last_triggered_at", "last_metric_value",
            "last_error", "created_at", "updated_at",
        )

    def validate_indicator(self, value):
        if value not in INDICATOR_SPECS:
            raise serializers.ValidationError(f"Unknown indicator: {value}")
        return value

    def validate_operator(self, value):
        if value not in OPERATORS:
            raise serializers.ValidationError(f"Unknown operator: {value}")
        return value

    def validate(self, attrs):
        # Validate the indicator params together with the indicator (handles both
        # full creates and partial updates by falling back to the instance).
        indicator = attrs.get("indicator") or getattr(self.instance, "indicator", None)
        params = attrs.get("params", getattr(self.instance, "params", None))
        if indicator:
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
            "threshold", "metric_value", "ai_used", "ai_rationale", "message",
            "delivery", "is_read", "created_at",
        )
        read_only_fields = fields
