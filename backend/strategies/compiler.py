"""Compile a React Flow node graph into strategy fields.

Expected graph: an ``asset`` node -> a ``quant`` node -> an ``ai`` node, connected
by edges. This is the "advanced" builder path; the plain form builder POSTs the
structured fields directly and never touches this module.
"""
from marketdata import INDICATOR_SPECS, OPERATORS


class GraphCompilationError(Exception):
    pass


def compile_graph(nodes: list, edges: list) -> dict:
    """Return ``{ticker, indicator, params, operator, threshold, ai_enabled, ai_prompt}``."""
    if not nodes:
        raise GraphCompilationError("Graph is empty.")

    node_map = {n.get("id"): n for n in nodes}

    asset_nodes = [n for n in nodes if n.get("type") == "asset"]
    if not asset_nodes:
        raise GraphCompilationError("Graph must contain an Asset node.")
    root = asset_nodes[0]

    pipeline = {"ai_enabled": False, "ai_prompt": "", "params": {}}
    ticker = (root.get("data") or {}).get("ticker")
    if not ticker:
        raise GraphCompilationError("Asset node is missing a ticker.")
    pipeline["ticker"] = ticker

    # Walk edges from the asset node; tolerate dangling edges.
    current = root.get("id")
    seen = set()
    have_quant = False
    while True:
        if current in seen:
            raise GraphCompilationError("Graph contains a cycle.")
        seen.add(current)
        outgoing = [e for e in edges if e.get("source") == current]
        if not outgoing:
            break
        target_id = outgoing[0].get("target")
        node = node_map.get(target_id)
        if node is None:
            raise GraphCompilationError(f"Edge points to unknown node {target_id!r}.")
        data = node.get("data") or {}
        ntype = node.get("type")
        if ntype == "quant":
            indicator = data.get("indicator")
            operator = data.get("operator")
            if indicator not in INDICATOR_SPECS:
                raise GraphCompilationError(f"Unknown indicator {indicator!r}.")
            if operator not in OPERATORS:
                raise GraphCompilationError(f"Unknown operator {operator!r}.")
            try:
                threshold = float(data.get("value"))
            except (TypeError, ValueError):
                raise GraphCompilationError("Quant node has an invalid threshold value.")
            pipeline["indicator"] = indicator
            pipeline["operator"] = operator
            pipeline["threshold"] = threshold
            pipeline["params"] = data.get("params") or {}
            have_quant = True
        elif ntype == "ai":
            pipeline["ai_enabled"] = True
            pipeline["ai_prompt"] = data.get("prompt", "") or ""
        current = target_id

    if not have_quant:
        raise GraphCompilationError("Strategy must connect an Asset node to a Quant node.")
    return pipeline
