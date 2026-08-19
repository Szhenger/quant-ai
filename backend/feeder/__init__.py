from .providers import get_provider, PriceSeries, ProviderError
from .indicators import (
    INDICATOR_SPECS,
    OPERATORS,
    compute_indicator,
    analyze_market,
    evaluate_condition,
    lookback_days,
    validate_params,
)
from .conditions import (
    ConditionError,
    validate_condition_tree,
    simple_condition,
    evaluate_condition_tree,
    evaluate_compare,
    replay_condition,
    condition_lookback_days,
    describe_tree,
    primary_metric,
    representative_fields,
)
from .stockpage import build_quantitative, build_qualitative

__all__ = [
    "get_provider",
    "PriceSeries",
    "ProviderError",
    "INDICATOR_SPECS",
    "OPERATORS",
    "compute_indicator",
    "analyze_market",
    "evaluate_condition",
    "lookback_days",
    "validate_params",
    # Composite conditions
    "ConditionError",
    "validate_condition_tree",
    "simple_condition",
    "evaluate_condition_tree",
    "evaluate_compare",
    "replay_condition",
    "condition_lookback_days",
    "describe_tree",
    "primary_metric",
    "representative_fields",
    # Stock-page compilation (watchlist MVP)
    "build_quantitative",
    "build_qualitative",
]
