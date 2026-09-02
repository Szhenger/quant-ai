"""Compile a React Flow node graph into a strategy's condition tree.

Node types:
  * ``asset`` — supplies the ticker (exactly one).
  * ``quant`` — one comparison. ``data`` = {indicator, params, operator, and a
    right operand: either ``value`` (constant) or ``right: {indicator, params}``
    for an indicator-vs-indicator comparison}.
  * ``logic`` — an AND/OR group. Its children are the ``quant``/``logic`` nodes
    whose edges point *into* it (source = child, target = this logic node).
  * ``ai``    — optional AI confirmation; ``data`` = {prompt}. Consumes the root
    condition node.

Returns ``{ticker, condition, ai_enabled, ai_prompt, indicator, operator,
threshold, params}`` — ``condition`` is the tree; the flat fields are a
representative leaf (kept for the default name / display). The plain form builder
POSTs structured fields directly and never touches this module.
"""
from markets import INDICATOR_SPECS, OPERATORS, representative_fields


class GraphCompilationError(Exception):
    pass


def _operand_from_data(data: dict) -> dict:
    """Build the right-hand operand of a comparison from a quant node's data."""
    right = data.get("right")
    if isinstance(right, dict) and right.get("indicator"):
        return {"indicator": right["indicator"], "params": right.get("params") or {}}
    raw = right["value"] if isinstance(right, dict) and "value" in right else data.get("value")
    try:
        return {"value": float(raw)}
    except (TypeError, ValueError):
        raise GraphCompilationError("Quant node has an invalid threshold value.") from None


def _compile_compare(node: dict) -> dict:
    data = node.get("data") or {}
    indicator = data.get("indicator")
    operator = data.get("operator")
    if indicator not in INDICATOR_SPECS:
        raise GraphCompilationError(f"Unknown indicator {indicator!r}.")
    if operator not in OPERATORS:
        raise GraphCompilationError(f"Unknown operator {operator!r}.")
    return {
        "type": "compare",
        "left": {"indicator": indicator, "params": data.get("params") or {}},
        "operator": operator,
        "right": _operand_from_data(data),
    }


def _find_root(condition_ids, ai_id, edges, node_map):
    """The condition node that is the tree's output: it feeds the AI node if one
    exists, otherwise it is the single condition node with no downstream condition."""
    if ai_id is not None:
        # dict.fromkeys: dedupe while keeping edge order — duplicate edges from a
        # single condition must not read as "multiple conditions".
        feeders = list(dict.fromkeys(
            e["source"] for e in edges
            if e.get("target") == ai_id and e.get("source") in condition_ids
        ))
        if len(feeders) > 1:
            raise GraphCompilationError(
                "Multiple conditions feed the AI node; "
                "combine them with a Logic (AND/OR) node first."
            )
        if feeders:
            return node_map[feeders[0]]
    sinks = [nid for nid in condition_ids
             if not any(e.get("source") == nid and e.get("target") in condition_ids
                        for e in edges)]
    if len(sinks) == 1:
        return node_map[sinks[0]]
    if not sinks:
        raise GraphCompilationError("Condition graph has a cycle or no output node.")
    raise GraphCompilationError(
        "Strategy has multiple disconnected conditions; "
        "connect them with a Logic (AND/OR) node."
    )


def _partition(nodes: list) -> dict:
    """Group nodes by type and enforce the required kinds. Returns
    ``{ticker, compares, logics, ais, node_map}``."""
    if not nodes:
        raise GraphCompilationError("Graph is empty.")
    by_type = {}
    for node in nodes:
        by_type.setdefault(node.get("type"), []).append(node)
    assets = by_type.get("asset", [])
    if not assets:
        raise GraphCompilationError("Graph must contain an Asset node.")
    ticker = (assets[0].get("data") or {}).get("ticker")
    if not ticker:
        raise GraphCompilationError("Asset node is missing a ticker.")
    compares = by_type.get("quant", [])
    if not compares:
        raise GraphCompilationError("Strategy must contain at least one Quant node.")
    return {
        "ticker": ticker,
        "compares": compares,
        "logics": by_type.get("logic", []),
        "ais": by_type.get("ai", []),
        "node_map": {n.get("id"): n for n in nodes},
    }


def _check_edges(edges: list, node_map: dict) -> None:
    """Reject edges to unknown nodes (once the required node kinds are present)."""
    for edge in edges:
        for endpoint in ("source", "target"):
            ref = edge.get(endpoint)
            if ref is not None and ref not in node_map:
                raise GraphCompilationError(f"Edge points to unknown node {ref!r}.")


def _compile_tree(root: dict, condition_ids: set, edges: list, node_map: dict):
    """Compile the condition tree rooted at ``root``. Returns ``(tree, visited)``
    so the caller can detect condition nodes the walk never reached."""
    def children_of(parent_id):
        return [
            node_map[edge["source"]]
            for edge in edges
            if edge.get("target") == parent_id and edge.get("source") in condition_ids
        ]

    visited = set()

    def compile_node(node, seen):
        nid = node["id"]
        if nid in seen:
            raise GraphCompilationError("Graph contains a cycle.")
        seen = seen | {nid}
        visited.add(nid)
        if node.get("type") == "logic":
            op = (node.get("data") or {}).get("op", "AND")
            if op not in ("AND", "OR"):
                raise GraphCompilationError(f"Logic node has invalid op {op!r}.")
            kids = children_of(nid)
            if not kids:
                raise GraphCompilationError("Logic (AND/OR) node has no inputs.")
            return {"type": "group", "op": op,
                    "children": [compile_node(k, seen) for k in kids]}
        return _compile_compare(node)

    return compile_node(root, set()), visited


def compile_graph(nodes: list, edges: list) -> dict:
    parts = _partition(nodes)
    node_map = parts["node_map"]
    _check_edges(edges, node_map)

    condition_ids = {n["id"] for n in parts["compares"] + parts["logics"]}
    ais = parts["ais"]
    ai_id = ais[0]["id"] if ais else None

    root = _find_root(condition_ids, ai_id, edges, node_map)
    tree, visited = _compile_tree(root, condition_ids, edges, node_map)

    # Every condition node must be reachable from the root: a quant/logic node
    # left unwired would otherwise be dropped silently, and the user would
    # believe a condition gates their alerts that in fact does nothing. (The
    # no-AI path already rejects this as "multiple disconnected conditions";
    # with an AI node the root comes from its feeder edge, so check explicitly.)
    orphans = condition_ids - visited
    if orphans:
        raise GraphCompilationError(
            "Condition node(s) not connected to the strategy output: "
            + ", ".join(sorted(orphans))
            + ". Wire them in with a Logic (AND/OR) node or remove them."
        )

    rep = representative_fields(tree)
    return {
        "ticker": parts["ticker"],
        "condition": tree,
        "ai_enabled": bool(ais),
        "ai_prompt": ((ais[0].get("data") or {}).get("prompt", "") if ais else "") or "",
        "indicator": rep.get("indicator"),
        "operator": rep.get("operator"),
        "threshold": rep.get("threshold"),
        "params": rep.get("params", {}),
    }
