"""Quantitative indicator library.

Pure, dependency-light (numpy) functions. Each indicator produces a full series
aligned to ``closes`` (with ``None`` during warm-up) so we can read both the
latest value and the previous value — the latter is needed for cross operators.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from .providers import get_provider

# --------------------------------------------------------------------------- #
# Indicator specs (drives the UI dropdowns + defaults + lookback sizing)
# --------------------------------------------------------------------------- #
# ``default_threshold`` seeds the strategy form with a threshold that sits on
# the indicator's own scale (a z-score lives in ±3σ, RSI in 0-100, …). Without
# it a form seeded for one indicator carries a nonsense threshold into another
# — "Z-Score < 30" is true on every bar and fires every cooldown window.
# ``None`` = price-scaled indicators, where no universal default exists and the
# user must choose.
# ``summary`` marks the fields a non-expert reads first — they lead the
# stock-page summary. ``readings`` turns a value into one plain-language
# phrase: an ordered list of bands on the field's own scale, each a condition
# in the same operator vocabulary as strategies (``{"op": "<", "at": 30,
# "text": "oversold"}``); the first band that holds wins, and a band with no
# ``op`` is the catch-all. Both live HERE, next to the math, so the stock page,
# the analysis table and the strategy builder all describe a field identically
# and a new indicator surfaces everywhere with no per-screen edits.
INDICATOR_SPECS: Dict[str, dict] = {
    "Z_SCORE": {"label": "Z-Score", "unit": "σ", "defaults": {"window": 20},
                "default_threshold": -2.0,
                "help": "Standard deviations the latest close sits from its rolling mean.",
                "summary": True,
                "readings": [
                    {"op": "<=", "at": -2.0, "text": "unusually cheap vs. its recent average"},
                    {"op": ">=", "at": 2.0, "text": "unusually expensive vs. its recent average"},
                    {"text": "near its recent average"},
                ]},
    "RSI": {"label": "RSI", "unit": "", "defaults": {"period": 14},
            "default_threshold": 30.0,
            "help": "Relative Strength Index (0-100). <30 oversold, >70 overbought.",
            "summary": True,
            "readings": [
                {"op": "<", "at": 30.0, "text": "oversold"},
                {"op": ">", "at": 70.0, "text": "overbought"},
                {"text": "neutral"},
            ]},
    "SMA_CROSS": {"label": "SMA Spread (fast-slow)", "unit": "$", "defaults": {"fast": 20, "slow": 50},
                  "default_threshold": 0.0,
                  "help": "Fast SMA minus slow SMA. Cross above 0 = golden cross.",
                  "summary": False,
                  "readings": [
                      {"op": ">", "at": 0.0, "text": "fast average above slow (uptrend)"},
                      {"op": "<", "at": 0.0, "text": "fast average below slow (downtrend)"},
                      {"text": "averages level"},
                  ]},
    "MACD_HIST": {"label": "MACD Histogram", "unit": "", "defaults": {"fast": 12, "slow": 26, "signal": 9},
                  "default_threshold": 0.0,
                  "help": "MACD line minus signal line.",
                  "summary": False,
                  "readings": [
                      {"op": ">", "at": 0.0, "text": "momentum building"},
                      {"op": "<", "at": 0.0, "text": "momentum fading"},
                      {"text": "momentum flat"},
                  ]},
    "PCT_CHANGE": {"label": "% Change", "unit": "%", "defaults": {"window": 1},
                   "default_threshold": -5.0,
                   "help": "Percent change of the close over N bars.",
                   "summary": True,
                   "readings": [
                       {"op": ">", "at": 0.0, "text": "up over the window"},
                       {"op": "<", "at": 0.0, "text": "down over the window"},
                       {"text": "flat"},
                   ]},
    "VOLATILITY": {"label": "Volatility (annualized)", "unit": "%", "defaults": {"window": 20},
                   "default_threshold": 40.0,
                   "help": "Annualized standard deviation of daily returns.",
                   "summary": True,
                   "readings": [
                       {"op": ">=", "at": 40.0, "text": "highly volatile"},
                       {"op": "<=", "at": 15.0, "text": "calm"},
                       {"text": "moderate volatility"},
                   ]},
    "SMA": {"label": "SMA", "unit": "$", "defaults": {"window": 20},
            "default_threshold": None,
            "help": "Simple moving average of the close over N bars.",
            "summary": False, "readings": []},
    "EMA": {"label": "EMA", "unit": "$", "defaults": {"window": 20},
            "default_threshold": None,
            "help": "Exponential moving average of the close over N bars.",
            "summary": False, "readings": []},
    "PRICE": {"label": "Price", "unit": "$", "defaults": {},
              "default_threshold": None,
              "help": "The latest closing price.",
              "summary": False, "readings": []},
}

# What a reading says when the field has no value yet (warm-up window).
NO_HISTORY_READING = "not enough history yet"

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

# Readings are plain comparisons on a single value; the cross operators need a
# previous value and make no sense as a band.
_READING_OPERATORS = {"<", ">", "<=", ">="}


def summary_indicators() -> List[str]:
    """Catalog order of the fields flagged ``summary`` — the stock-page headline set."""
    return [key for key, spec in INDICATOR_SPECS.items() if spec.get("summary")]


def read_indicator(indicator: str, value: Optional[float]) -> str:
    """One plain-language phrase for ``value`` on this field's scale, from the
    field's own ``readings`` bands. Empty string when the field defines none."""
    if value is None:
        return NO_HISTORY_READING
    for band in INDICATOR_SPECS[indicator].get("readings", []):
        op = band.get("op")
        if op is None or evaluate_condition(op, value, None, float(band["at"])):
            return band["text"]
    return ""


def _check_specs() -> None:
    """Fail at import, not at 3am, if a spec entry is malformed."""
    for key, spec in INDICATOR_SPECS.items():
        for field in ("label", "unit", "defaults", "default_threshold", "help", "summary", "readings"):
            if field not in spec:
                raise ValueError(f"INDICATOR_SPECS[{key!r}] is missing {field!r}")
        bands = spec["readings"]
        for i, band in enumerate(bands):
            if "text" not in band:
                raise ValueError(f"INDICATOR_SPECS[{key!r}].readings[{i}] has no text")
            if "op" in band:
                if band["op"] not in _READING_OPERATORS or "at" not in band:
                    raise ValueError(f"INDICATOR_SPECS[{key!r}].readings[{i}] is not a comparison")
            elif i != len(bands) - 1:
                raise ValueError(f"INDICATOR_SPECS[{key!r}]: the catch-all reading must be last")


# Upper bound for every window/period parameter. Without a ceiling, a strategy
# with e.g. {"window": 10**9} passes validation, the lookback sizing asks for
# billions of bars, and the synthetic fallback provider will happily generate
# them — an authenticated OOM/CPU DoS against the worker or the web tier
# (analysis/replay compute in-request). 500 trading days ≈ 2 years, comfortably
# above any sane indicator window.
PARAM_MAXIMUM = 500

# Hard ceiling on how much history a single evaluation may request, regardless
# of parameters — defence in depth behind PARAM_MAXIMUM.
MAX_LOOKBACK_DAYS = 2500

# Minimum value each per-indicator parameter may take (defends against degenerate
# configs like window=1, which yields NaN, or fast >= slow on crossovers).
_PARAM_MINIMUMS = {
    "Z_SCORE": {"window": 2},
    "RSI": {"period": 2},
    "SMA_CROSS": {"fast": 1, "slow": 2},
    "MACD_HIST": {"fast": 1, "slow": 2, "signal": 1},
    "PCT_CHANGE": {"window": 1},
    "VOLATILITY": {"window": 2},
    "SMA": {"window": 1},
    "EMA": {"window": 1},
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
            raise ValueError(f"Parameter '{name}' must be an integer.") from None
        floor = minimums.get(name, 1)
        if value < floor:
            raise ValueError(f"Parameter '{name}' must be at least {floor}.")
        if value > PARAM_MAXIMUM:
            raise ValueError(f"Parameter '{name}' must be at most {PARAM_MAXIMUM}.")
        merged[name] = value
    if indicator in ("SMA_CROSS", "MACD_HIST") and merged["fast"] >= merged["slow"]:
        raise ValueError("The fast window must be smaller than the slow window.")
    return merged


def lookback_days(indicator: str, params: Optional[dict] = None) -> int:
    """How many trading days of history an indicator needs (with headroom)."""
    params = {**INDICATOR_SPECS.get(indicator, {}).get("defaults", {}), **(params or {})}
    longest = max([1] + [v for v in params.values() if isinstance(v, (int, float))])
    return int(min(MAX_LOOKBACK_DAYS, max(120, longest * 4)))


# --------------------------------------------------------------------------- #
# Series builders
# --------------------------------------------------------------------------- #
def _sma(closes: List[float], window: int) -> List[Optional[float]]:
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < window:
        return out
    # sliding_window_view is a zero-copy view; the whole sweep runs in C instead
    # of one np.mean call per bar (~100x on a 2500-bar / 500-window series).
    arr = np.asarray(closes, dtype=float)
    out[window - 1:] = sliding_window_view(arr, window).mean(axis=1).tolist()
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


def _ema_series(closes: List[float], window: int) -> List[Optional[float]]:
    """EMA with the first ``window - 1`` bars masked to ``None``: the recursion is
    seeded at the first close, so early values are biased toward it — unmasked
    they could fire replay/live conditions on bars that aren't warmed up."""
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    ema = _ema(closes, window)
    for i in range(window - 1, n):
        out[i] = float(ema[i])
    return out


def _zscore_series(closes: List[float], window: int) -> List[Optional[float]]:
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < window:
        return out
    arr = np.asarray(closes, dtype=float)
    win = sliding_window_view(arr, window)
    mean = win.mean(axis=1)
    std = win.std(axis=1, ddof=1)
    flat = std == 0
    z = (arr[window - 1:] - mean) / np.where(flat, 1.0, std)
    z[flat] = 0.0  # a flat window is zero deviations, not a division by zero
    out[window - 1:] = z.tolist()
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
    return [(fv - sv) if (fv is not None and sv is not None) else None
            for fv, sv in zip(f, s, strict=True)]


def _macd_hist_series(closes: List[float], fast: int, slow: int, signal: int) -> List[Optional[float]]:
    n = len(closes)
    if n < slow + signal:
        return [None] * n
    macd = _ema(closes, fast) - _ema(closes, slow)
    hist = macd - _ema(macd.tolist(), signal)
    # Mask the full warm-up region — the slow EMA AND the signal-line EMA over
    # it — matching the ``n >= slow + signal`` sufficiency guard above. Anything
    # shorter exposes seed-biased values whose fires shift with how much
    # history the provider happened to return.
    out: List[Optional[float]] = [None] * n
    for i in range(slow + signal - 1, n):
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
    # Row j of the window view is rets[j:j+window] — the window ENDING before
    # bar j+window, so out[i] takes row i-window (trailing returns only).
    stds = sliding_window_view(rets, window).std(axis=1, ddof=1)
    out[window:] = (stds[: n - window] * np.sqrt(252) * 100.0).tolist()
    return out


_BUILDERS = {
    "Z_SCORE": lambda c, p: _zscore_series(c, int(p["window"])),
    "RSI": lambda c, p: _rsi_series(c, int(p["period"])),
    "SMA_CROSS": lambda c, p: _sma_cross_series(c, int(p["fast"]), int(p["slow"])),
    "MACD_HIST": lambda c, p: _macd_hist_series(c, int(p["fast"]), int(p["slow"]), int(p["signal"])),
    "PCT_CHANGE": lambda c, p: _pct_change_series(c, int(p["window"])),
    "VOLATILITY": lambda c, p: _volatility_series(c, int(p["window"])),
    "SMA": lambda c, p: _sma(c, int(p["window"])),
    "EMA": lambda c, p: _ema_series(c, int(p["window"])),
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
        # Report the TRUE source of these bars, not the configured primary: if the
        # provider degraded to synthetic data, say "synthetic", never "yfinance".
        "provider": "synthetic" if series.synthetic else provider.name,
        "synthetic": series.synthetic,
        "dates": series.dates,
        "closes": closes,
        "latest_price": series.latest,
        "indicators": indicators,
    }


_check_specs()
