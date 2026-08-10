import math

import pytest

from feeder import compute_indicator, evaluate_condition, validate_params, OPERATORS


def test_zscore_value():
    closes = [10, 10, 10, 10, 12]
    result = compute_indicator("Z_SCORE", closes, {"window": 5})
    # mean=10.4, sample std=0.8944 -> z = 1.6/0.8944 ≈ 1.789
    assert result["value"] == pytest.approx(1.789, abs=1e-3)


def test_zscore_flat_series_is_zero():
    result = compute_indicator("Z_SCORE", [5, 5, 5, 5, 5], {"window": 5})
    assert result["value"] == 0.0


def test_rsi_bounds_and_uptrend():
    closes = list(range(1, 40))  # strictly increasing
    result = compute_indicator("RSI", closes, {"period": 14})
    assert result["value"] == pytest.approx(100.0, abs=1e-6)


def test_pct_change():
    result = compute_indicator("PCT_CHANGE", [100, 110], {"window": 1})
    assert result["value"] == pytest.approx(10.0)


def test_price_indicator_returns_last_close():
    result = compute_indicator("PRICE", [1, 2, 3.5])
    assert result["value"] == 3.5


def test_ema_warmup_is_masked():
    # The EMA recursion is seeded at the first close; the biased warm-up region
    # must be None so warm-up bars can never fire a condition.
    result = compute_indicator("EMA", [10.0] * 25, {"window": 20})
    assert result["series"][:19] == [None] * 19
    assert result["series"][19] == pytest.approx(10.0)
    assert result["value"] == pytest.approx(10.0)


def test_insufficient_history_returns_none():
    result = compute_indicator("Z_SCORE", [10], {"window": 20})
    assert result["value"] is None


@pytest.mark.parametrize("op,value,prev,thr,expected", [
    ("<", -2.5, None, -2.0, True),
    ("<", -1.0, None, -2.0, False),
    (">", 3.0, None, 2.0, True),
    (">=", 2.0, None, 2.0, True),
    ("cross_above", 1.0, -1.0, 0.0, True),
    ("cross_above", 1.0, 0.5, 0.0, False),
    ("cross_below", -1.0, 1.0, 0.0, True),
    ("cross_below", 1.0, 2.0, 0.0, False),
])
def test_evaluate_condition(op, value, prev, thr, expected):
    assert evaluate_condition(op, value, prev, thr) is expected


def test_evaluate_condition_none_value_is_false():
    assert evaluate_condition("<", None, None, 0.0) is False


def test_unknown_indicator_raises():
    with pytest.raises(ValueError):
        compute_indicator("NOPE", [1, 2, 3])


# --- Param validation (L3) + operators (L2) ---------------------------------

def test_validate_params_fills_defaults():
    assert validate_params("Z_SCORE", None) == {"window": 20}


def test_validate_params_rejects_degenerate_window():
    with pytest.raises(ValueError):
        validate_params("Z_SCORE", {"window": 1})  # would produce NaN


def test_validate_params_rejects_fast_ge_slow():
    with pytest.raises(ValueError):
        validate_params("SMA_CROSS", {"fast": 50, "slow": 20})


def test_validate_params_rejects_non_integer():
    with pytest.raises(ValueError):
        validate_params("RSI", {"period": "abc"})


def test_equality_operator_not_offered():
    # "==" is a footgun on continuous indicators; it must not be selectable.
    assert "==" not in OPERATORS
