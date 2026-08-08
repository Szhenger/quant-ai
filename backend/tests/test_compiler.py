import pytest

from strategies.compiler import compile_graph, GraphCompilationError


def _graph():
    return {
        "nodes": [
            {"id": "n1", "type": "asset", "data": {"ticker": "AAPL"}},
            {"id": "n2", "type": "quant",
             "data": {"indicator": "Z_SCORE", "operator": "<", "value": -2.0}},
            {"id": "n3", "type": "ai", "data": {"prompt": "Is the thesis broken?"}},
        ],
        "edges": [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
        ],
    }


def test_compile_valid_graph():
    g = _graph()
    p = compile_graph(g["nodes"], g["edges"])
    assert p["ticker"] == "AAPL"
    assert p["indicator"] == "Z_SCORE"
    assert p["operator"] == "<"
    assert p["threshold"] == -2.0
    assert p["ai_enabled"] is True
    assert p["ai_prompt"] == "Is the thesis broken?"
    # A single quant node compiles to a one-leaf condition tree.
    assert p["condition"] == {
        "type": "compare",
        "left": {"indicator": "Z_SCORE", "params": {}},
        "operator": "<",
        "right": {"value": -2.0},
    }


def test_compile_composite_and_graph():
    # RSI < 30  AND  PRICE crosses above SMA(50), joined by a Logic (AND) node.
    nodes = [
        {"id": "asset", "type": "asset", "data": {"ticker": "MSFT"}},
        {"id": "c1", "type": "quant",
         "data": {"indicator": "RSI", "operator": "<", "value": 30}},
        {"id": "c2", "type": "quant",
         "data": {"indicator": "PRICE", "operator": "cross_above",
                  "right": {"indicator": "SMA", "params": {"window": 50}}}},
        {"id": "and", "type": "logic", "data": {"op": "AND"}},
        {"id": "ai", "type": "ai", "data": {"prompt": "confirm"}},
    ]
    edges = [
        {"source": "asset", "target": "c1"},
        {"source": "c1", "target": "and"},
        {"source": "c2", "target": "and"},
        {"source": "and", "target": "ai"},
    ]
    p = compile_graph(nodes, edges)
    assert p["ticker"] == "MSFT"
    assert p["ai_enabled"] is True
    tree = p["condition"]
    assert tree["type"] == "group" and tree["op"] == "AND"
    kinds = {c["left"]["indicator"] for c in tree["children"]}
    assert kinds == {"RSI", "PRICE"}
    price_leaf = next(c for c in tree["children"] if c["left"]["indicator"] == "PRICE")
    assert price_leaf["right"] == {"indicator": "SMA", "params": {"window": 50}}
    # Representative flat fields come from the first leaf.
    assert p["indicator"] == "RSI"


def test_compile_rejects_disconnected_conditions():
    nodes = [
        {"id": "asset", "type": "asset", "data": {"ticker": "AAPL"}},
        {"id": "c1", "type": "quant", "data": {"indicator": "RSI", "operator": "<", "value": 30}},
        {"id": "c2", "type": "quant", "data": {"indicator": "PRICE", "operator": ">", "value": 0}},
    ]
    edges = [{"source": "asset", "target": "c1"}]  # c1 and c2 both sinks, no Logic node
    with pytest.raises(GraphCompilationError, match="disconnected"):
        compile_graph(nodes, edges)


def test_compile_logic_node_without_inputs():
    nodes = [
        {"id": "asset", "type": "asset", "data": {"ticker": "AAPL"}},
        {"id": "c1", "type": "quant", "data": {"indicator": "RSI", "operator": "<", "value": 30}},
        {"id": "and", "type": "logic", "data": {"op": "AND"}},
        {"id": "ai", "type": "ai", "data": {"prompt": "x"}},
    ]
    # The AND node feeds the AI but nothing feeds the AND.
    edges = [{"source": "asset", "target": "c1"}, {"source": "and", "target": "ai"}]
    with pytest.raises(GraphCompilationError, match="no inputs"):
        compile_graph(nodes, edges)


def test_missing_asset_node():
    g = _graph()
    g["nodes"] = [n for n in g["nodes"] if n["type"] != "asset"]
    with pytest.raises(GraphCompilationError, match="Asset node"):
        compile_graph(g["nodes"], g["edges"])


def test_missing_quant_node():
    g = _graph()
    g["nodes"] = [n for n in g["nodes"] if n["type"] != "quant"]
    g["edges"] = [{"source": "n1", "target": "n3"}]
    with pytest.raises(GraphCompilationError, match="Quant node"):
        compile_graph(g["nodes"], g["edges"])


def test_dangling_edge():
    g = _graph()
    g["edges"].append({"source": "n3", "target": "ghost"})
    with pytest.raises(GraphCompilationError, match="unknown node"):
        compile_graph(g["nodes"], g["edges"])


def test_ai_optional():
    g = _graph()
    g["nodes"] = [n for n in g["nodes"] if n["type"] != "ai"]
    g["edges"] = [{"source": "n1", "target": "n2"}]
    p = compile_graph(g["nodes"], g["edges"])
    assert p["ai_enabled"] is False
