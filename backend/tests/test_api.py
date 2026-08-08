import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core.models import Workspace
from strategies.models import Strategy

pytestmark = pytest.mark.django_db


def test_register_creates_default_workspace(client=None):
    api = APIClient()
    resp = api.post("/api/v1/auth/register/", {
        "username": "newbie", "email": "n@example.com", "password": "s3cretpw!"
    }, format="json")
    assert resp.status_code == 201
    user = get_user_model().objects.get(username="newbie")
    assert Workspace.objects.filter(owner=user).count() == 1


def test_create_strategy(auth_client, workspace):
    resp = auth_client.post("/api/v1/strategies/", {
        "name": "AAPL oversold",
        "ticker": "aapl",
        "indicator": "Z_SCORE",
        "params": {"window": 20},
        "operator": "<",
        "threshold": -2.0,
        "ai_enabled": False,
    }, format="json")
    assert resp.status_code == 201, resp.content
    assert resp.data["ticker"] == "AAPL"  # normalised
    assert Strategy.objects.filter(workspace=workspace).count() == 1


def test_strategy_requires_workspace_header(user):
    from rest_framework_simplejwt.tokens import RefreshToken
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    resp = api.get("/api/v1/strategies/")  # no X-Workspace-ID
    assert resp.status_code == 403


def test_tenant_isolation(auth_client):
    # A strategy in someone else's workspace must not be visible.
    other = get_user_model().objects.create_user(username="other", password="pw!")
    other_ws = Workspace.objects.create(name="Other", owner=other)
    Strategy.objects.create(
        workspace=other_ws, name="secret", ticker="TSLA",
        indicator="PRICE", operator=">", threshold=1,
    )
    resp = auth_client.get("/api/v1/strategies/")
    assert resp.status_code == 200
    assert resp.data["count"] == 0


def test_deploy_graph(auth_client, workspace):
    resp = auth_client.post("/api/v1/strategies/deploy-graph/", {
        "name": "Graph strat",
        "nodes": [
            {"id": "n1", "type": "asset", "data": {"ticker": "MSFT"}},
            {"id": "n2", "type": "quant",
             "data": {"indicator": "RSI", "operator": "<", "value": 30}},
            {"id": "n3", "type": "ai", "data": {"prompt": "check"}},
        ],
        "edges": [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
        ],
    }, format="json")
    assert resp.status_code == 201, resp.content
    s = Strategy.objects.get(workspace=workspace)
    assert s.ticker == "MSFT"
    assert s.indicator == "RSI"
    assert s.ai_enabled is True


def test_indicator_catalog(auth_client):
    resp = auth_client.get("/api/v1/indicators/")
    assert resp.status_code == 200
    keys = {i["key"] for i in resp.data["indicators"]}
    assert {"Z_SCORE", "RSI", "PRICE"}.issubset(keys)


def test_market_analysis(auth_client):
    resp = auth_client.get("/api/v1/markets/AAPL/analysis/")
    assert resp.status_code == 200
    assert resp.data["ticker"] == "AAPL"
    assert len(resp.data["closes"]) > 20
    assert "Z_SCORE" in resp.data["indicators"]


def _strategy_payload(**overrides):
    payload = {
        "name": "s", "ticker": "AAPL", "indicator": "Z_SCORE",
        "params": {"window": 20}, "operator": "<", "threshold": -2.0,
        "ai_enabled": False,
    }
    payload.update(overrides)
    return payload


def test_create_fills_default_params(auth_client, workspace):
    resp = auth_client.post("/api/v1/strategies/",
                            _strategy_payload(params={}), format="json")
    assert resp.status_code == 201, resp.content
    assert Strategy.objects.get(workspace=workspace).params == {"window": 20}


def test_reject_degenerate_window(auth_client):
    resp = auth_client.post("/api/v1/strategies/",
                            _strategy_payload(params={"window": 1}), format="json")
    assert resp.status_code == 400
    assert "params" in resp.data


def test_reject_fast_ge_slow(auth_client):
    resp = auth_client.post("/api/v1/strategies/", _strategy_payload(
        indicator="SMA_CROSS", params={"fast": 50, "slow": 20}), format="json")
    assert resp.status_code == 400


def test_reject_zero_cooldown(auth_client):
    resp = auth_client.post("/api/v1/strategies/",
                            _strategy_payload(cooldown_minutes=0), format="json")
    assert resp.status_code == 400


def test_reject_equality_operator(auth_client):
    resp = auth_client.post("/api/v1/strategies/",
                            _strategy_payload(operator="=="), format="json")
    assert resp.status_code == 400


def test_indicator_catalog_excludes_equality(auth_client):
    resp = auth_client.get("/api/v1/indicators/")
    ops = {o["key"] for o in resp.data["operators"]}
    assert "==" not in ops
    assert {"<", ">", "cross_above"}.issubset(ops)
