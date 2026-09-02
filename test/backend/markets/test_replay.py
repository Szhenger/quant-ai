"""Signal replay: the deterministic 'would this have fired?' timeline."""
import pytest

from markets import replay_condition, simple_condition, validate_condition_tree


def _tree(indicator, op, right):
    right = {"value": right} if not isinstance(right, dict) else right
    return validate_condition_tree(
        {"type": "compare", "left": {"indicator": indicator}, "operator": op, "right": right}
    )


def test_always_true_fires_every_bar():
    closes = [1.0, 2.0, 3.0, 4.0]
    r = replay_condition(validate_condition_tree(simple_condition("PRICE", ">", 0.0)), closes)
    assert r["bars"] == 4
    assert r["fire_count"] == 4
    assert [f["index"] for f in r["fires"]] == [0, 1, 2, 3]


def test_never_true_never_fires():
    r = replay_condition(_tree("PRICE", ">", 1e12), [1.0, 2.0, 3.0])
    assert r["fire_count"] == 0


def test_cooldown_bars_dedupes_a_persistent_condition():
    closes = [1.0] * 10  # PRICE > 0 holds on every bar
    r = replay_condition(_tree("PRICE", ">", 0.0), closes, cooldown_bars=3)
    # Fires, then suppressed for 3 bars each time — measured from the last fire.
    assert [f["index"] for f in r["fires"]] == [0, 3, 6, 9]


def test_cross_fires_only_at_the_crossing_bar():
    closes = [10.0, 8.0, 12.0, 11.0, 9.0, 13.0]
    tree = _tree("PRICE", "cross_above", {"indicator": "SMA", "params": {"window": 2}})
    r = replay_condition(tree, closes)
    assert [f["index"] for f in r["fires"]] == [2, 5]


def test_replay_carries_dates_and_metric():
    closes = [5.0, 6.0]
    dates = ["2026-01-01", "2026-01-02"]
    r = replay_condition(validate_condition_tree(simple_condition("PRICE", ">", 0.0)), closes, dates)
    assert r["fires"][0]["date"] == "2026-01-01"
    assert r["fires"][1]["metric"] == pytest.approx(6.0)


def test_replay_matches_live_eval_on_the_last_bar():
    # The last bar of a replay must agree with the live single-shot evaluation.
    from markets import evaluate_condition_tree

    closes = [10, 10, 10, 10, 12]
    tree = validate_condition_tree(simple_condition("Z_SCORE", ">", 1.0, {"window": 5}))
    live = evaluate_condition_tree(tree, closes)["result"]
    replay = replay_condition(tree, closes)
    last_fired = any(f["index"] == len(closes) - 1 for f in replay["fires"])
    assert last_fired is live
