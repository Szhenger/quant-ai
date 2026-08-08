from rest_framework import serializers

from marketdata import (
    INDICATOR_SPECS,
    OPERATORS,
    validate_params,
    validate_condition_tree,
    representative_fields,
)
from .models import Strategy, Alert


class StrategySerializer(serializers.ModelSerializer):
    # Composite mode: an AND/OR condition tree. When present it is authoritative
    # and the flat indicator/operator/threshold columns are derived from it.
    condition = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = Strategy
        fields = (
            "id", "name", "ticker",
            "indicator", "params", "operator", "threshold", "condition",
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
        # In composite mode the client sends only `condition`; the flat columns are
        # filled server-side, so they must not be required at the field level.
        extra_kwargs = {
            "indicator": {"required": False},
            "operator": {"required": False},
            "threshold": {"required": False},
        }

    def validate_indicator(self, value):
        if value not in INDICATOR_SPECS:
            raise serializers.ValidationError(f"Unknown indicator: {value}")
        return value

    def validate_operator(self, value):
        if value not in OPERATORS:
            raise serializers.ValidationError(f"Unknown operator: {value}")
        return value

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
            "threshold", "metric_value", "ai_used", "ai_rationale", "message",
            "condition_detail", "data_synthetic", "delivery", "is_read", "created_at",
        )
        read_only_fields = fields
