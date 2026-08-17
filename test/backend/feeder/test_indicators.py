"""Indicator math, pinned to hand-derived numbers.

Every expected value below is computed by hand (or with the ``statistics``
module) from the chapter definitions in ``math/`` — never by re-running the
code under test. If an implementation change moves a number, that's a change
to the math, and this file is where it gets noticed.
"""
import math
import statistics

import pytest

from feeder.indicators import (
    INDICATOR_SPECS,
    MAX_LOOKBACK_DAYS,
    PARAM_MAXIMUM,
    compute_indicator,
    evaluate_condition,
    lookback_days,
    validate_params,
)


# --------------------------------------------------------------------------- #
# Simple moving average
# --------------------------------------------------------------------------- #
def test_sma_is_the_rolling_mean_with_warmup_masked():
    result = compute_indicator("SMA", [1.0, 2.0, 3.0, 4.0, 5.0], {"window": 3})
    assert result["series"] == [None, None, 2.0, 3.0, 4.0]
    assert result["value"] == 4.0
    assert result["previous"] == 3.0


def test_sma_shorter_than_window_is_all_none():
    result = compute_indicator("SMA", [1.0, 2.0], {"window": 3})
    assert result["series"] == [None, None]
    assert result["value"] is None
    assert result["previous"] is None


# --------------------------------------------------------------------------- #
# Exponential moving average
# --------------------------------------------------------------------------- #
def test_ema_recursion_hand_computed():
    # window 3 → alpha = 2/(3+1) = 0.5, seeded at the first close:
    #   e0 = 2, e1 = .5*4 + .5*2 = 3, e2 = .5*8 + .5*3 = 5.5
    # and the first window-1 = 2 bars are masked as warm-up.
    result = compute_indicator("EMA", [2.0, 4.0, 8.0], {"window": 3})
    assert result["series"] == [None, None, pytest.approx(5.5)]


def test_ema_of_a_constant_series_is_the_constant():
    result = compute_indicator("EMA", [7.0] * 10, {"window": 4})
    assert all(v == pytest.approx(7.0) for v in result["series"][3:])


# --------------------------------------------------------------------------- #
# Z-score
# --------------------------------------------------------------------------- #
def test_zscore_matches_sample_statistics():
    closes = [1.0, 2.0, 3.0, 4.0, 10.0]
    window = closes[-3:]
    expected = (closes[-1] - statistics.mean(window)) / statistics.stdev(window)
    result = compute_indicator("Z_SCORE", closes, {"window": 3})
    assert result["value"] == pytest.approx(expected)


def test_zscore_of_a_flat_window_is_zero_not_a_division_error():
    result = compute_indicator("Z_SCORE", [5.0] * 8, {"window": 4})
    assert result["series"][3:] == [0.0] * 5


# --------------------------------------------------------------------------- #
# RSI (Wilder smoothing)
# --------------------------------------------------------------------------- #
def test_rsi_is_100_on_all_gains_and_0_on_all_losses():
    up = compute_indicator("RSI", [1.0, 2.0, 3.0, 4.0], {"period": 2})
    down = compute_indicator("RSI", [4.0, 3.0, 2.0, 1.0], {"period": 2})
    assert up["value"] == 100.0
    assert down["value"] == 0.0


def test_rsi_wilder_smoothing_hand_computed():
    # closes [10, 11, 10.5, 11.5], period 2:
    #   deltas [+1, -0.5, +1] → gains [1, 0, 1], losses [0, 0.5, 0]
    #   seed: avg_gain = 0.5, avg_loss = 0.25 → RS = 2 → RSI = 66.666…
    #   next: avg_gain = (0.5·1 + 1)/2 = 0.75, avg_loss = (0.25·1 + 0)/2 = 0.125
    #         RS = 6 → RSI = 100 − 100/7 = 85.714…
    result = compute_indicator("RSI", [10.0, 11.0, 10.5, 11.5], {"period": 2})
    assert result["series"][:2] == [None, None]
    assert result["series"][2] == pytest.approx(100 - 100 / 3)
    assert result["series"][3] == pytest.approx(100 - 100 / 7)


def test_rsi_stays_inside_its_bounds():
    closes = [100.0 + math.sin(i / 3.0) * 7 for i in range(80)]
    result = compute_indicator("RSI", closes, {"period": 14})
    values = [v for v in result["series"] if v is not None]
    assert values and all(0.0 <= v <= 100.0 for v in values)


# --------------------------------------------------------------------------- #
# SMA cross spread
# --------------------------------------------------------------------------- #
def test_sma_cross_is_fast_minus_slow():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = compute_indicator("SMA_CROSS", closes, {"fast": 2, "slow": 3})
    # fast SMA(2)[-1] = 4.5, slow SMA(3)[-1] = 4 → spread 0.5; warm-up follows
    # the slower window.
    assert result["series"][:2] == [None, None]
    assert result["value"] == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# MACD histogram
# --------------------------------------------------------------------------- #
def test_macd_hist_hand_computed():
    # fast=1 (EMA = the closes themselves), slow=2 (alpha 2/3), signal=2 on
    # closes [2, 4, 8, 16]:
    #   slow EMA  = [2, 10/3, 58/9, 346/27]
    #   MACD      = [0, 2/3, 14/9, 86/27]
    #   signal    = [0, 4/9, 32/27, 68/27]
    #   histogram = MACD − signal = [0, 2/9, 10/27, 18/27]
    # with the first slow+signal-1 = 3 bars masked as warm-up (the slow EMA
    # AND the signal line over it must both be warm).
    result = compute_indicator("MACD_HIST", [2.0, 4.0, 8.0, 16.0],
                               {"fast": 1, "slow": 2, "signal": 2})
    assert result["series"][:3] == [None, None, None]
    assert result["series"][3] == pytest.approx(18 / 27)


def test_macd_hist_too_short_is_all_none():
    result = compute_indicator("MACD_HIST", [1.0, 2.0],
                               {"fast": 1, "slow": 2, "signal": 2})
    assert result["series"] == [None, None]


# --------------------------------------------------------------------------- #
# Percent change
# --------------------------------------------------------------------------- #
def test_pct_change_hand_computed():
    result = compute_indicator("PCT_CHANGE", [100.0, 110.0], {"window": 1})
    assert result["series"] == [None, pytest.approx(10.0)]


def test_pct_change_over_a_zero_base_is_none_not_infinity():
    result = compute_indicator("PCT_CHANGE", [0.0, 5.0], {"window": 1})
    assert result["series"] == [None, None]


# --------------------------------------------------------------------------- #
# Annualized volatility
# --------------------------------------------------------------------------- #
def test_volatility_matches_sample_stdev_times_sqrt252():
    closes = [100.0, 101.0, 102.0, 101.0]
    rets = [(b - a) / a for a, b in zip(closes, closes[1:])]
    expected = statistics.stdev(rets[:2]) * math.sqrt(252) * 100.0
    result = compute_indicator("VOLATILITY", closes, {"window": 2})
    assert result["series"][2] == pytest.approx(expected)


def test_volatility_of_a_constant_series_is_zero():
    result = compute_indicator("VOLATILITY", [50.0] * 10, {"window": 3})
    assert all(v == pytest.approx(0.0) for v in result["series"][3:])


# --------------------------------------------------------------------------- #
# compute_indicator envelope
# --------------------------------------------------------------------------- #
def test_series_is_always_aligned_to_closes():
    closes = [float(i) for i in range(1, 40)]
    for key in INDICATOR_SPECS:
        result = compute_indicator(key, closes)
        assert len(result["series"]) == len(closes), key


def test_unknown_indicator_is_rejected():
    with pytest.raises(ValueError, match="Unknown indicator"):
        compute_indicator("VIBES", [1.0, 2.0])


# --------------------------------------------------------------------------- #
# Parameter validation (the DoS guardrails)
# --------------------------------------------------------------------------- #
def test_validate_params_merges_defaults_and_coerces_ints():
    assert validate_params("Z_SCORE", {"window": "25"}) == {"window": 25}
    assert validate_params("Z_SCORE", None) == {"window": 20}


@pytest.mark.parametrize("params", [{"window": "twenty"}, {"window": None}])
def test_validate_params_rejects_non_integers(params):
    with pytest.raises(ValueError, match="must be an integer"):
        validate_params("SMA", params)


def test_validate_params_enforces_floor_and_ceiling():
    with pytest.raises(ValueError, match="at least 2"):
        validate_params("Z_SCORE", {"window": 1})
    with pytest.raises(ValueError, match=f"at most {PARAM_MAXIMUM}"):
        validate_params("SMA", {"window": PARAM_MAXIMUM + 1})


def test_validate_params_rejects_fast_not_below_slow():
    with pytest.raises(ValueError, match="fast window must be smaller"):
        validate_params("SMA_CROSS", {"fast": 50, "slow": 20})


def test_lookback_has_a_floor_and_a_hard_ceiling():
    assert lookback_days("PRICE") == 120           # floor
    assert lookback_days("SMA", {"window": 200}) == 800   # 4× headroom
    assert lookback_days("SMA", {"window": 700}) == MAX_LOOKBACK_DAYS  # capped


# --------------------------------------------------------------------------- #
# Condition operators
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("op,value,prev,threshold,expected", [
    ("<", 1.0, None, 2.0, True),
    (">", 1.0, None, 2.0, False),
    ("<=", 2.0, None, 2.0, True),
    (">=", 2.0, None, 2.0, True),
    ("cross_above", 2.0, 1.0, 1.5, True),    # rose through the threshold
    ("cross_above", 2.0, 1.5, 1.5, True),    # exactly-at counts as below
    ("cross_above", 2.0, 1.6, 1.5, False),   # was already above
    ("cross_below", 1.0, 2.0, 1.5, True),
    ("cross_below", 1.0, 1.4, 1.5, False),   # was already below
])
def test_operator_semantics(op, value, prev, threshold, expected):
    assert evaluate_condition(op, value, prev, threshold) is expected


def test_missing_values_never_fire():
    assert evaluate_condition(">", None, None, 0.0) is False
    assert evaluate_condition("cross_above", 2.0, None, 1.0) is False


def test_unknown_operator_is_rejected():
    with pytest.raises(ValueError, match="Unknown operator"):
        evaluate_condition("==", 1.0, 1.0, 1.0)
