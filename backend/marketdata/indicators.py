"""Quantitative indicator library.

Pure, dependency-light (numpy) functions. Each indicator produces a full series
aligned to ``closes`` (with ``None`` during warm-up) so we can read both the
latest value and the previous value — the latter is needed for cross operators.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from .providers import get_provider

# --------------------------------------------------------------------------- #
# Indicator specs (drives the UI dropdowns + defaults + lookback sizing)
# --------------------------------------------------------------------------- #
INDICATOR_SPECS: Dict[str, dict] = {
    "Z_SCORE": {"label": "Z-Score", "unit": "σ", "defaults": {"window": 20},
                "help": "Standard deviations the latest close sits from its rolling mean."},
    "RSI": {"label": "RSI", "unit": "", "defaults": {"period": 14},
            "help": "Relative Strength Index (0-100). <30 oversold, >70 overbought."},
    "SMA_CROSS": {"label": "SMA Spread (fast-slow)", "unit": "$", "defaults": {"fast": 20, "slow": 50},
                  "help": "Fast SMA minus slow SMA. Cross above 0 = golden cross."},
    "MACD_HIST": {"label": "MACD Histogram", "unit": "", "defaults": {"fast": 12, "slow": 26, "signal": 9},
                  "help": "MACD line minus signal line."},
    "PCT_CHANGE": {"label": "% Change", "unit": "%", "defaults": {"window": 1},
                   "help": "Percent change of the close over N bars."},
    "VOLATILITY": {"label": "Volatility (annualized)", "unit": "%", "defaults": {"window": 20},
                   "help": "Annualized standard deviation of daily returns."},
    "PRICE": {"label": "Price", "unit": "$", "defaults": {},
              "help": "The latest closing price."},
}

# Operators available for conditions. Cross operators use the previous value.
# NOTE: exact float equality ("==") is intentionally NOT offered — a computed
# indicator (z-score, RSI, MACD, …) essentially never lands on an exact value, so
# an "==" rule would silently never fire. Use crosses / thresholds instead.
OPERATORS = {
    "<": "less than",
    ">": "greater than",
    "<=": "at most",
    ">=": "at least",
    "cross_above": "crosses above",
    "cross_below": "crosses below",
}

# Minimum value each per-indicator parameter may take (defends against degenerate
# configs like window=1, which yields NaN, or fast >= slow on crossovers).
_PARAM_MINIMUMS = {
    "Z_SCORE": {"window": 2},
    "RSI": {"period": 2},
    "SMA_CROSS": {"fast": 1, "slow": 2},
    "MACD_HIST": {"fast": 1, "slow": 2, "signal": 1},
    "PCT_CHANGE": {"window": 1},
    "VOLATILITY": {"window": 2},
    "PRICE": {},
}


def validate_params(indicator: str, params: Optional[dict]) -> dict:
    """Validate + normalise indicator parameters, returning the merged dict.

    Raises ``ValueError`` with a human-readable message on any invalid config.
    """
    if indicator not in INDICATOR_SPECS:
        raise ValueError(f"Unknown indicator: {indicator}")
    merged = {**INDICATOR_SPECS[indicator]["defaults"], **(params or {})}
    minimums = _PARAM_MINIMUMS.get(indicator, {})
    for name, raw in merged.items():
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"Parameter '{name}' must be an integer.")
        floor = minimums.get(name, 1)
        if value < floor:
            raise ValueError(f"Parameter '{name}' must be at least {floor}.")
        merged[name] = value
    if indicator in ("SMA_CROSS", "MACD_HIST") and merged["fast"] >= merged["slow"]:
        raise ValueError("The fast window must be smaller than the slow window.")
    return merged


def lookback_days(indicator: str, params: Optional[dict] = None) -> int:
    """How many trading days of history an indicator needs (with headroom)."""
    params = {**INDICATOR_SPECS.get(indicator, {}).get("defaults", {}), **(params or {})}
    longest = max([1] + [v for v in params.values() if isinstance(v, (int, float))])
    return int(max(120, longest * 4))


# --------------------------------------------------------------------------- #
# Series builders
# --------------------------------------------------------------------------- #
def _sma(closes: List[float], window: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    for i in range(window - 1, len(closes)):
        out[i] = float(np.mean(closes[i - window + 1:i + 1]))
    return out


def _ema(values: List[float], span: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return arr
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(arr)
    out[0] = arr[0]
    for i in range(1, arr.size):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def _zscore_series(closes: List[float], window: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    for i in range(window - 1, len(closes)):
        w = np.asarray(closes[i - window + 1:i + 1], dtype=float)
        std = w.std(ddof=1)
        out[i] = 0.0 if std == 0 else float((closes[i] - w.mean()) / std)
    return out


def _rsi_series(closes: List[float], period: int) -> List[Optional[float]]:
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < period + 1:
        return out
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    def rsi_val(ag: float, al: float) -> float:
        if al == 0:
            return 100.0
        rs = ag / al
        return float(100 - 100 / (1 + rs))

    avg_gain = float(gains[:period].mean())
    avg_loss = float(losses[:period].mean())
    out[period] = rsi_val(avg_gain, avg_loss)
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = rsi_val(avg_gain, avg_loss)
    return out


def _sma_cross_series(closes: List[float], fast: int, slow: int) -> List[Optional[float]]:
    f = _sma(closes, fast)
    s = _sma(closes, slow)
    return [(fv - sv) if (fv is not None and sv is not None) else None for fv, sv in zip(f, s)]


def _macd_hist_series(closes: List[float], fast: int, slow: int, signal: int) -> List[Optional[float]]:
    n = len(closes)
    if n < slow + signal:
        return [None] * n
    macd = _ema(closes, fast) - _ema(closes, slow)
    hist = macd - _ema(macd.tolist(), signal)
    # Mask the warm-up region where the slow EMA is unreliable.
    out: List[Optional[float]] = [None] * n
    for i in range(slow, n):
        out[i] = float(hist[i])
    return out


def _pct_change_series(closes: List[float], window: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    for i in range(window, len(closes)):
        prev = closes[i - window]
        if prev:
            out[i] = float((closes[i] - prev) / prev * 100)
    return out


def _volatility_series(closes: List[float], window: int) -> List[Optional[float]]:
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < window + 1:
        return out
    closes_arr = np.asarray(closes, dtype=float)
    rets = np.diff(closes_arr) / closes_arr[:-1]  # length n-1, rets[i] is return into bar i+1
    for i in range(window, n):
        w = rets[i - window:i]
        out[i] = float(np.std(w, ddof=1) * np.sqrt(252) * 100)
    return out


_BUILDERS = {
    "Z_SCORE": lambda c, p: _zscore_series(c, int(p["window"])),
    "RSI": lambda c, p: _rsi_series(c, int(p["period"])),
    "SMA_CROSS": lambda c, p: _sma_cross_series(c, int(p["fast"]), int(p["slow"])),
    "MACD_HIST": lambda c, p: _macd_hist_series(c, int(p["fast"]), int(p["slow"]), int(p["signal"])),
    "PCT_CHANGE": lambda c, p: _pct_change_series(c, int(p["window"])),
    "VOLATILITY": lambda c, p: _volatility_series(c, int(p["window"])),
    "PRICE": lambda c, p: [float(x) for x in c],
}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def compute_indicator(indicator: str, closes: List[float], params: Optional[dict] = None) -> dict:
    """Compute an indicator over ``closes``.

    Returns ``{value, previous, series, indicator, params, unit, label}``.
    ``value``/``previous`` are ``None`` when there isn't enough history.
    """
    if indicator not in _BUILDERS:
        raise ValueError(f"Unknown indicator: {indicator!r}")
    spec = INDICATOR_SPECS[indicator]
    merged = {**spec.get("defaults", {}), **(params or {})}
    series = _BUILDERS[indicator](closes, merged)

    def last_valid(offset: int) -> Optional[float]:
        seen = 0
        for v in reversed(series):
            if v is not None:
                if seen == offset:
                    return v
                seen += 1
        return None

    return {
        "indicator": indicator,
        "label": spec["label"],
        "unit": spec["unit"],
        "params": merged,
        "value": last_valid(0),
        "previous": last_valid(1),
        "series": series,
    }


def evaluate_condition(operator: str, value: Optional[float],
                       previous: Optional[float], threshold: float) -> bool:
    """Return True when ``value`` (with ``previous`` for cross ops) satisfies the
    condition ``value <operator> threshold``."""
    if value is None:
        return False
    if operator == "<":
        return value < threshold
    if operator == ">":
        return value > threshold
    if operator == "<=":
        return value <= threshold
    if operator == ">=":
        return value >= threshold
    if operator == "==":
        return value == threshold
    if operator == "cross_above":
        return previous is not None and previous <= threshold < value
    if operator == "cross_below":
        return previous is not None and previous >= threshold > value
    raise ValueError(f"Unknown operator: {operator!r}")


def analyze_market(ticker: str, days: int = 180) -> dict:
    """Full quantitative snapshot for the market-analysis dashboard."""
    provider = get_provider()
    series = provider.history(ticker, days=days)
    closes = series.closes
    indicators = {}
    for key in INDICATOR_SPECS:
        try:
            result = compute_indicator(key, closes)
            indicators[key] = {
                "label": result["label"],
                "unit": result["unit"],
                "value": result["value"],
                "params": result["params"],
            }
        except Exception:  # noqa: BLE001
            indicators[key] = None
    return {
        "ticker": series.ticker,
        "provider": provider.name,
        "dates": series.dates,
        "closes": closes,
        "latest_price": series.latest,
        "indicators": indicators,
    }
