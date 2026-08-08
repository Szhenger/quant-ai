"""Composite condition-tree engine (marketdata/conditions.py) + SMA/EMA indicators."""
import pytest

from marketdata import (
    ConditionError,
    compute_indicator,
    condition_lookback_days,
    describe_tree,
    evaluate_compare,
    evaluate_condition,
    evaluate_condition_tree,
    primary_metric,
    simple_condition,
    validate_condition_tree,
)


# --- New standalone indicators ---------------------------------------------
def test_sma_indicator_is_rolling_mean():
    result = compute_indicator("SMA", [10, 20, 30], {"window": 2})
    assert result["value"] == pytest.approx(25.0)     # mean(20, 30)
    assert result["previous"] == pytest.approx(15.0)   # mean(10, 20)


def test_ema_indicator_runs_and_tracks_price():
    result = compute_indicator("EMA", [10, 10, 10, 10, 20], {"window": 3})
    # EMA lags a step change but sits between the old level and the new close.
    assert 10.0 < result["value"] < 20.0


# --- evaluate_compare: generalises the scalar path -------------------------
@pytest.mark.parametrize("op,lv,lp,rv,rp,expected", [
    ("<", 1.0, None, 2.0, None, True),
    (">", 3.0, None, 2.0, None, True),
    (">=", 2.0, None, 2.0, None, True),
    ("cross_above", 12.0, 8.0, 10.0, 9.0, True),    # left crosses above right series
    ("cross_above", 12.0, 11.0, 10.0, 9.0, False),  # already above last bar
    ("cross_below", 8.0, 12.0, 10.0, 9.0, True),
    ("cross_below", 8.0, 7.0, 10.0, 9.0, False),
])
def test_evaluate_compare(op, lv, lp, rv, rp, expected):
    assert evaluate_compare(lv, lp, rv, rp, op) is expected


def test_evaluate_compare_none_is_false():
    assert evaluate_compare(None, None, 1.0, 1.0, "<") is False
    assert evaluate_compare(1.0, 1.0, None, None, "<") is False


def test_compare_reduces_to_scalar_for_constant_right():
    # With a constant right operand, evaluate_compare must agree with the scalar
    # evaluate_condition for every operator (constant => value == previous).
    for op, value, prev, thr in [
        ("<", -2.5, None, -2.0),
        (">", 3.0, None, 2.0),
        ("cross_above", 1.0, -1.0, 0.0),
        ("cross_below", -1.0, 1.0, 0.0),
    ]:
        scalar = evaluate_condition(op, value, prev, thr)
        general = evaluate_compare(value, prev, thr, thr, op)
        assert scalar == general


# --- Validation ------------------------------------------------------------
def _leaf(indicator="RSI", op="<", right=None):
    right = {"value": 30} if right is None else right
    return {"type": "compare", "left": {"indicator": indicator}, "operator": op, "right": right}


def test_validate_normalises_params_and_defaults():
    tree = validate_condition_tree(_leaf("RSI", "<", {"value": 30}))
    assert tree["left"]["params"] == {"period": 14}       # default filled in
    assert tree["right"] == {"value": 30.0}


def test_validate_indicator_vs_indicator():
    tree = validate_condition_tree(
        _leaf("PRICE", "cross_above", {"indicator": "SMA", "params": {"window": 50}})
    )
    assert tree["right"]["indicator"] == "SMA"
    assert tree["right"]["params"] == {"window": 50}


def test_validate_rejects_unknown_indicator():
    with pytest.raises(ConditionError):
        validate_condition_tree(_leaf("NOPE"))


def test_validate_rejects_unknown_operator():
    with pytest.raises(ConditionError):
        validate_condition_tree(_leaf("RSI", "=="))


def test_validate_rejects_constant_left():
    with pytest.raises(ConditionError):
        validate_condition_tree(
            {"type": "compare", "left": {"value": 5}, "operator": "<", "right": {"value": 30}}
        )


def test_validate_rejects_degenerate_params():
    with pytest.raises(ConditionError):
        validate_condition_tree(
            {"type": "compare", "left": {"indicator": "Z_SCORE", "params": {"window": 1}},
             "operator": "<", "right": {"value": 0}}
        )


def test_validate_rejects_too_deeply_nested():
    node = _leaf()
    for _ in range(10):
        node = {"type": "group", "op": "AND", "children": [node]}
    with pytest.raises(ConditionError):
        validate_condition_tree(node)


def test_validate_rejects_empty_group():
    with pytest.raises(ConditionError):
        validate_condition_tree({"type": "group", "op": "AND", "children": []})


# --- Evaluation ------------------------------------------------------------
def test_and_group_requires_all_true():
    closes = [10, 10, 10, 10, 12]  # Z_SCORE(window=5) ~ 1.789, PRICE = 12
    tree = validate_condition_tree({
        "type": "group", "op": "AND", "children": [
            {"type": "compare", "left": {"indicator": "Z_SCORE", "params": {"window": 5}},
             "operator": ">", "right": {"value": 1.0}},
            {"type": "compare", "left": {"indicator": "PRICE"},
             "operator": ">", "right": {"value": 11.0}},
        ],
    })
    assert evaluate_condition_tree(tree, closes)["result"] is True

    # Break the second leaf -> AND is False, but OR would still be True.
    tree["children"][1]["right"]["value"] = 100.0
    assert evaluate_condition_tree(tree, closes)["result"] is False
    tree["op"] = "OR"
    assert evaluate_condition_tree(tree, closes)["result"] is True


def test_indicator_vs_indicator_cross():
    closes = [10, 8, 12]  # price dips below its SMA(2) then closes back above it
    tree = validate_condition_tree(
        _leaf("PRICE", "cross_above", {"indicator": "SMA", "params": {"window": 2}})
    )
    out = evaluate_condition_tree(tree, closes)
    assert out["result"] is True
    # The audit detail carries the concrete operand values that produced the fire.
    assert out["detail"]["left"]["value"] == pytest.approx(12.0)
    assert out["detail"]["right"]["value"] == pytest.approx(10.0)  # SMA(2) of [8, 12]


def test_simple_condition_matches_scalar_path():
    closes = [10, 10, 10, 10, 12]
    tree = validate_condition_tree(simple_condition("Z_SCORE", ">", 1.0, {"window": 5}))
    result = compute_indicator("Z_SCORE", closes, {"window": 5})
    assert (
        evaluate_condition_tree(tree, closes)["result"]
        is evaluate_condition(">", result["value"], result["previous"], 1.0)
    )


# --- Introspection ---------------------------------------------------------
def test_condition_lookback_takes_the_max():
    tree = validate_condition_tree({
        "type": "group", "op": "AND", "children": [
            _leaf("RSI", "<", {"value": 30}),
            _leaf("PRICE", "cross_above", {"indicator": "SMA", "params": {"window": 200}}),
        ],
    })
    # SMA(200) needs 200*4 = 800 days; that dominates.
    assert condition_lookback_days(tree) == 800


def test_primary_metric_is_first_leaf_left_value():
    closes = [10, 10, 10, 10, 12]
    tree = validate_condition_tree(simple_condition("PRICE", ">", 0.0))
    detail = evaluate_condition_tree(tree, closes)["detail"]
    assert primary_metric(detail) == pytest.approx(12.0)


def test_describe_tree_reads_naturally():
    tree = validate_condition_tree({
        "type": "group", "op": "AND", "children": [
            _leaf("RSI", "<", {"value": 30}),
            _leaf("PRICE", "cross_above", {"indicator": "SMA", "params": {"window": 50}}),
        ],
    })
    text = describe_tree(tree)
    assert "RSI less than 30" in text
    assert "crosses above" in text
    assert "SMA(window=50)" in text
    assert " AND " in text
