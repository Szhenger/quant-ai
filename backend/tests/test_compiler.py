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
