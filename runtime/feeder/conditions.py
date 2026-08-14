"""Composite condition trees.

A strategy's firing condition can be a single comparison ("RSI < 30") or a tree
of comparisons combined with AND/OR, where each side of a comparison is either a
constant or another indicator ("PRICE crosses above SMA(window=50)").

Tree schema (JSON)::

    group   = {"type": "group", "op": "AND"|"OR", "children": [node, ...]}
    compare = {"type": "compare",
               "left":  {"indicator": <key>, "params": {...}},
               "operator": <op>,
               "right": {"value": <number>} | {"indicator": <key>, "params": {...}}}

The scalar single-comparison helper ``evaluate_condition`` in ``indicators`` is
left untouched; this module is the general case and reduces to it exactly when a
comparison's right side is a constant (``value == previous == threshold``).
"""
from __future__ import annotations

import json
import math
from typing import List, Optional, Tuple

from .indicators import (
    INDICATOR_SPECS,
    OPERATORS,
    compute_indicator,
    lookback_days,
    validate_params,
)

# Guardrails against pathological trees (deeply nested / huge payloads).
MAX_NODES = 32
MAX_DEPTH = 6

# Comparison operators are exactly the ones the scalar path already offers
# (inequalities + crosses); "==" is intentionally excluded upstream.
_COMPARE_OPERATORS = set(OPERATORS)


class ConditionError(ValueError):
    """Raised for a malformed condition tree. A ``ValueError`` so serializer /
    validation call sites that already catch ``ValueError`` keep working."""


# --------------------------------------------------------------------------- #
# Validation / normalisation
# --------------------------------------------------------------------------- #
def _validate_operand(operand, *, side: str, require_indicator: bool) -> dict:
    if not isinstance(operand, dict):
        raise ConditionError(f"{side} operand must be an object.")
    has_indicator = "indicator" in operand
    has_value = "value" in operand
    if has_indicator and has_value:
        raise ConditionError(f"{side} operand cannot be both an indicator and a constant.")
    if not has_indicator and not has_value:
        raise ConditionError(f"{side} operand must specify an 'indicator' or a 'value'.")
    if has_value:
        if require_indicator:
            raise ConditionError(f"{side} operand must be an indicator, not a constant.")
        try:
            value = float(operand["value"])
        except (TypeError, ValueError):
            raise ConditionError(f"{side} operand constant must be a number.")
        # NaN never compares true (a rule that silently never fires) and
        # non-finite values render as invalid strict JSON in payloads.
        if not math.isfinite(value):
            raise ConditionError(f"{side} operand constant must be a finite number.")
        return {"value": value}
    indicator = operand["indicator"]
    if indicator not in INDICATOR_SPECS:
        raise ConditionError(f"Unknown indicator: {indicator!r}.")
    try:
        params = validate_params(indicator, operand.get("params"))
    except ValueError as exc:
        raise ConditionError(str(exc))
    return {"indicator": indicator, "params": params}


def _validate_node(node, depth: int, counter: dict) -> dict:
    counter["n"] += 1
    if counter["n"] > MAX_NODES:
        raise ConditionError(f"Condition has too many nodes (max {MAX_NODES}).")
    if depth > MAX_DEPTH:
        raise ConditionError(f"Condition nesting is too deep (max depth {MAX_DEPTH}).")
    if not isinstance(node, dict):
        raise ConditionError("Each condition node must be an object.")

    ntype = node.get("type")
    if ntype == "group":
        op = node.get("op")
        if op not in ("AND", "OR"):
            raise ConditionError("Group 'op' must be 'AND' or 'OR'.")
        children = node.get("children")
        if not isinstance(children, list) or not children:
            raise ConditionError("A group must have at least one child.")
        return {
            "type": "group",
            "op": op,
            "children": [_validate_node(c, depth + 1, counter) for c in children],
        }
    if ntype == "compare":
        operator = node.get("operator")
        if operator not in _COMPARE_OPERATORS:
            raise ConditionError(f"Unknown operator: {operator!r}.")
        return {
            "type": "compare",
            "left": _validate_operand(node.get("left"), side="Left", require_indicator=True),
            "operator": operator,
            "right": _validate_operand(node.get("right"), side="Right", require_indicator=False),
        }
    raise ConditionError(f"Unknown condition node type: {ntype!r}.")


def validate_condition_tree(tree) -> dict:
    """Validate + normalise a condition tree, returning its canonical form.

    Raises ``ConditionError`` (a ``ValueError``) on anything malformed.
    """
    if tree is None:
        raise ConditionError("Condition is empty.")
    return _validate_node(tree, depth=1, counter={"n": 0})


def simple_condition(indicator: str, operator: str, threshold: float,
                     params: Optional[dict] = None) -> dict:
    """Bridge a flat (indicator, operator, threshold) rule into a one-leaf tree.

    Lets the evaluator take a single code path whether a strategy was authored in
    simple mode or with the composite builder.
    """
    return {
        "type": "compare",
        "left": {"indicator": indicator, "params": params or {}},
        "operator": operator,
        "right": {"value": float(threshold)},
    }


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def evaluate_compare(
    left_value: Optional[float],
    left_prev: Optional[float],
    right_value: Optional[float],
    right_prev: Optional[float],
    operator: str,
) -> bool:
    """Compare two operands (each a value + its previous value).

    A constant operand passes ``value == previous``, so this is a strict
    generalisation of the scalar ``evaluate_condition``.
    """
    if left_value is None or right_value is None:
        return False
    if operator == "<":
        return left_value < right_value
    if operator == ">":
        return left_value > right_value
    if operator == "<=":
        return left_value <= right_value
    if operator == ">=":
        return left_value >= right_value
    if operator == "cross_above":
        return (left_prev is not None and right_prev is not None
                and left_prev <= right_prev and left_value > right_value)
    if operator == "cross_below":
        return (left_prev is not None and right_prev is not None
                and left_prev >= right_prev and left_value < right_value)
    raise ConditionError(f"Unknown operator: {operator!r}.")


def _operand_values(operand, closes, cache) -> Tuple[Optional[float], Optional[float]]:
    """(value, previous) for an operand, memoising each distinct indicator series."""
    if "value" in operand:
        c = float(operand["value"])
        return c, c
    key = (operand["indicator"], json.dumps(operand.get("params") or {}, sort_keys=True))
    if key not in cache:
        result = compute_indicator(operand["indicator"], closes, operand.get("params"))
        cache[key] = (result["value"], result["previous"])
    return cache[key]


def _eval_node(node, closes, cache) -> dict:
    if node["type"] == "group":
        children = [_eval_node(c, closes, cache) for c in node["children"]]
        results = [c["result"] for c in children]
        result = all(results) if node["op"] == "AND" else any(results)
        return {"type": "group", "op": node["op"], "result": result, "children": children}
    lv, lprev = _operand_values(node["left"], closes, cache)
    rv, rprev = _operand_values(node["right"], closes, cache)
    return {
        "type": "compare",
        "operator": node["operator"],
        "left": {**node["left"], "value": lv, "previous": lprev},
        "right": {**node["right"], "value": rv, "previous": rprev},
        "result": evaluate_compare(lv, lprev, rv, rprev, node["operator"]),
    }


def evaluate_condition_tree(tree, closes) -> dict:
    """Evaluate a validated ``tree`` over ``closes``.

    Returns ``{"result": bool, "detail": <evaluated tree>}`` where every leaf in
    ``detail`` carries the concrete operand values that produced it — the audit
    trail we persist on the alert.
    """
    detail = _eval_node(tree, closes, {})
    return {"result": detail["result"], "detail": detail}


# --------------------------------------------------------------------------- #
# Signal replay — the deterministic "would this have fired?" timeline
# --------------------------------------------------------------------------- #
def _operand_full_series(operand, closes, cache) -> List[Optional[float]]:
    """The operand's value at every bar (a constant operand is a flat series)."""
    if "value" in operand:
        return [float(operand["value"])] * len(closes)
    key = (operand["indicator"], json.dumps(operand.get("params") or {}, sort_keys=True))
    if key not in cache:
        cache[key] = compute_indicator(operand["indicator"], closes, operand.get("params"))["series"]
    return cache[key]


def _prev_valid(series, i) -> Optional[float]:
    """Last non-``None`` value strictly before bar ``i``.

    Mirrors live evaluation's ``last_valid`` (which skips interior ``None``s,
    e.g. PCT_CHANGE over a zero close), so a cross evaluates identically in
    replay and live — replay is sold as "exactly what live would do".
    """
    for j in range(i - 1, -1, -1):
        if series[j] is not None:
            return series[j]
    return None


def _eval_node_at(node, i, closes, cache) -> dict:
    """Evaluate a node as of bar ``i`` — value = series[i], previous = the last
    valid value before ``i``."""
    if node["type"] == "group":
        children = [_eval_node_at(c, i, closes, cache) for c in node["children"]]
        results = [c["result"] for c in children]
        result = all(results) if node["op"] == "AND" else any(results)
        return {"type": "group", "op": node["op"], "result": result, "children": children}
    left = _operand_full_series(node["left"], closes, cache)
    right = _operand_full_series(node["right"], closes, cache)
    lv, lprev = left[i], _prev_valid(left, i)
    rv, rprev = right[i], _prev_valid(right, i)
    return {
        "type": "compare",
        "operator": node["operator"],
        "left": {**node["left"], "value": lv, "previous": lprev},
        "right": {**node["right"], "value": rv, "previous": rprev},
        "result": evaluate_compare(lv, lprev, rv, rprev, node["operator"]),
    }


def replay_condition(tree, closes, dates=None, cooldown_bars: int = 0) -> dict:
    """Walk ``closes`` bar by bar and record every bar where ``tree`` would fire.

    Deterministic and offline — no AI, no network. This is *signal replay*: a
    would-fire timeline, not a P&L backtest. ``cooldown_bars`` mirrors the live
    cooldown: after a recorded fire, further fires within N bars are suppressed
    (measured from the last *recorded* fire, exactly as the live system measures
    from the last alert). Evaluation at ``i`` uses each operand's value at bar
    ``i`` and its last valid prior value (same semantics as live evaluation),
    so warm-up bars simply never fire.

    Returns ``{"bars", "fire_count", "fires": [{index, date, metric}]}``.
    """
    cache: dict = {}
    n = len(closes)
    fires: List[dict] = []
    last_fire = None
    for i in range(n):
        node = _eval_node_at(tree, i, closes, cache)
        if not node["result"]:
            continue
        if last_fire is not None and cooldown_bars > 0 and (i - last_fire) < cooldown_bars:
            continue
        last_fire = i
        fires.append({
            "index": i,
            "date": dates[i] if dates is not None and i < len(dates) else None,
            "metric": primary_metric(node),
        })
    return {"bars": n, "fire_count": len(fires), "fires": fires}


# --------------------------------------------------------------------------- #
# Introspection helpers (lookback sizing, display, primary metric)
# --------------------------------------------------------------------------- #
def _collect_indicator_operands(node, out: list) -> None:
    if node["type"] == "group":
        for child in node["children"]:
            _collect_indicator_operands(child, out)
        return
    for side in ("left", "right"):
        operand = node[side]
        if "indicator" in operand:
            out.append((operand["indicator"], operand.get("params")))


def condition_lookback_days(tree) -> int:
    """Trading days of history the whole tree needs (max over its indicators)."""
    operands: List[tuple] = []
    _collect_indicator_operands(tree, operands)
    if not operands:
        return 120
    return max(lookback_days(indicator, params) for indicator, params in operands)


def _first_compare(node) -> Optional[dict]:
    if node["type"] == "compare":
        return node
    for child in node["children"]:
        found = _first_compare(child)
        if found is not None:
            return found
    return None


def primary_metric(detail) -> Optional[float]:
    """A single representative number for display: the first comparison's left value."""
    leaf = _first_compare(detail)
    return leaf["left"]["value"] if leaf else None


def representative_fields(tree) -> dict:
    """Best-effort flat ``{indicator, params, operator, threshold}`` for the legacy
    columns and simple-mode display, taken from the tree's first comparison.

    ``threshold`` is ``0.0`` when that comparison is indicator-vs-indicator (there
    is no scalar threshold). Returns ``{}`` for an (impossible) leaf-less tree.
    """
    leaf = _first_compare(tree)
    if leaf is None:
        return {}
    right = leaf["right"]
    return {
        "indicator": leaf["left"]["indicator"],
        "params": leaf["left"].get("params") or {},
        "operator": leaf["operator"],
        "threshold": float(right["value"]) if "value" in right else 0.0,
    }


def _operand_label(operand) -> str:
    if "indicator" in operand:
        indicator = operand["indicator"]
        spec = INDICATOR_SPECS.get(indicator, {})
        label = spec.get("label", indicator)
        params = operand.get("params") or {}
        defaults = spec.get("defaults", {})
        extra = {k: v for k, v in params.items() if defaults.get(k) != v}
        if extra:
            inner = ",".join(f"{k}={v}" for k, v in sorted(extra.items()))
            return f"{label}({inner})"
        return label
    value = operand.get("value")
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def describe_tree(node) -> str:
    """Human-readable one-line description, e.g. ``(RSI < 30 AND PRICE crosses above SMA)``.

    Accepts either a canonical tree or an evaluated ``detail`` tree.
    """
    if node["type"] == "group":
        joiner = f" {node['op']} "
        return "(" + joiner.join(describe_tree(c) for c in node["children"]) + ")"
    op_label = OPERATORS.get(node["operator"], node["operator"])
    return f"{_operand_label(node['left'])} {op_label} {_operand_label(node['right'])}"
