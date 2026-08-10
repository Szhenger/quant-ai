import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from identity.models import Workspace
from engine.models import Strategy

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


def test_create_composite_strategy(auth_client, workspace):
    resp = auth_client.post("/api/v1/strategies/", {
        "name": "RSI + trend",
        "ticker": "aapl",
        "ai_enabled": False,
        "condition": {
            "type": "group", "op": "AND", "children": [
                {"type": "compare", "left": {"indicator": "RSI"},
                 "operator": "<", "right": {"value": 30}},
                {"type": "compare", "left": {"indicator": "PRICE"}, "operator": "cross_above",
                 "right": {"indicator": "SMA", "params": {"window": 50}}},
            ],
        },
    }, format="json")
    assert resp.status_code == 201, resp.content
    s = Strategy.objects.get(workspace=workspace)
    assert s.condition["type"] == "group"
    # Composite mode fills default params inside the tree...
    assert s.condition["children"][0]["left"]["params"] == {"period": 14}
    # ...and derives representative flat columns from the first leaf.
    assert s.indicator == "RSI"
    assert s.operator == "<"
    assert s.threshold == 30.0


def test_reject_invalid_composite_condition(auth_client):
    resp = auth_client.post("/api/v1/strategies/", {
        "name": "bad", "ticker": "AAPL", "ai_enabled": False,
        "condition": {"type": "compare", "left": {"indicator": "NOPE"},
                      "operator": "<", "right": {"value": 1}},
    }, format="json")
    assert resp.status_code == 400
    assert "condition" in resp.data


def test_indicator_catalog(auth_client):
    resp = auth_client.get("/api/v1/indicators/")
    assert resp.status_code == 200
    keys = {i["key"] for i in resp.data["indicators"]}
    assert {"Z_SCORE", "RSI", "PRICE"}.issubset(keys)


def test_replay_endpoint(auth_client, workspace):
    s = Strategy.objects.create(
        workspace=workspace, name="r", ticker="AAPL",
        indicator="PRICE", operator=">", threshold=0.0, ai_enabled=False,
    )
    resp = auth_client.post(f"/api/v1/strategies/{s.id}/replay/", {"days": 120}, format="json")
    assert resp.status_code == 200, resp.content
    # PRICE > 0 holds on every synthetic bar, so it "would have fired" throughout.
    assert resp.data["synthetic"] is True          # honest about the data source
    assert resp.data["provider"] == "synthetic"
    assert resp.data["fire_count"] >= 30
    assert len(resp.data["closes"]) >= 120
    assert resp.data["fires"][0]["date"] is not None


def test_replay_cooldown_thins_fires(auth_client, workspace):
    s = Strategy.objects.create(
        workspace=workspace, name="r2", ticker="AAPL",
        indicator="PRICE", operator=">", threshold=0.0, ai_enabled=False,
    )
    raw = auth_client.post(f"/api/v1/strategies/{s.id}/replay/", {"days": 120}, format="json")
    cd = auth_client.post(
        f"/api/v1/strategies/{s.id}/replay/", {"days": 120, "cooldown_bars": 10}, format="json"
    )
    assert cd.data["fire_count"] < raw.data["fire_count"]


def test_replay_window_matches_requested_days(auth_client, workspace):
    s = Strategy.objects.create(
        workspace=workspace, name="w", ticker="AAPL",
        indicator="Z_SCORE", params={"window": 20},
        operator=">", threshold=-100.0, ai_enabled=False,
    )
    resp = auth_client.post(f"/api/v1/strategies/{s.id}/replay/", {"days": 60}, format="json")
    assert resp.status_code == 200, resp.content
    # The response covers exactly the requested window...
    assert resp.data["bars"] == 60
    assert len(resp.data["closes"]) == 60
    assert len(resp.data["dates"]) == 60
    # ...with lookback fetched on top, so even the first reported bar is warmed
    # up and can fire (z > -100 holds whenever the z-score is defined).
    assert resp.data["fires"][0]["index"] == 0
    assert all(0 <= f["index"] < 60 for f in resp.data["fires"])
    assert resp.data["fire_count"] == len(resp.data["fires"])


def test_watchlist_duplicate_ticker_is_rejected(auth_client):
    first = auth_client.post("/api/v1/watchlist/", {"ticker": "AAPL"}, format="json")
    assert first.status_code == 201, first.content
    # Same ticker (any casing/whitespace) must be a 400, not an IntegrityError 500.
    dup = auth_client.post("/api/v1/watchlist/", {"ticker": "aapl"}, format="json")
    assert dup.status_code == 400
    assert "ticker" in dup.data


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


def test_reject_private_webhook_urls(auth_client):
    # SSRF guard: the worker POSTs webhooks from inside our network, so
    # loopback / private / link-local (cloud metadata) targets must be 400s.
    for bad in ("http://127.0.0.1/hook", "http://10.0.0.5/hook",
                "http://169.254.169.254/latest/meta-data/", "ftp://example.com/x"):
        resp = auth_client.post("/api/v1/strategies/",
                                _strategy_payload(webhook_url=bad), format="json")
        assert resp.status_code == 400, bad
        assert "webhook_url" in resp.data, bad


def test_accept_public_webhook_url(auth_client, workspace):
    resp = auth_client.post("/api/v1/strategies/",
                            _strategy_payload(webhook_url="https://93.184.216.34/hook"),
                            format="json")
    assert resp.status_code == 201, resp.content
    s = Strategy.objects.get(workspace=workspace)
    assert s.webhook_url == "https://93.184.216.34/hook"
    assert len(s.webhook_secret) == 32  # auto-generated HMAC secret


def test_reject_malformed_ticker(auth_client):
    resp = auth_client.post("/api/v1/strategies/",
                            _strategy_payload(ticker="AA PL!"), format="json")
    assert resp.status_code == 400
    assert "ticker" in resp.data


def test_watchlist_rejects_malformed_ticker(auth_client):
    resp = auth_client.post("/api/v1/watchlist/", {"ticker": "NOT A TICKER"},
                            format="json")
    assert resp.status_code == 400
    assert "ticker" in resp.data


def test_deploy_graph_accepts_delivery_and_scheduling(auth_client, workspace):
    resp = auth_client.post("/api/v1/strategies/deploy-graph/", {
        "name": "Configured graph",
        "nodes": [
            {"id": "n1", "type": "asset", "data": {"ticker": "MSFT"}},
            {"id": "n2", "type": "quant",
             "data": {"indicator": "RSI", "operator": "<", "value": 30}},
        ],
        "edges": [{"source": "n1", "target": "n2"}],
        "notify_in_app": False,
        "notify_email": True,
        "webhook_url": "https://93.184.216.34/hook",
        "poll_interval_minutes": 5,
        "cooldown_minutes": 30,
    }, format="json")
    assert resp.status_code == 201, resp.content
    s = Strategy.objects.get(workspace=workspace)
    assert s.notify_in_app is False
    assert s.notify_email is True
    assert s.webhook_url == "https://93.184.216.34/hook"
    assert s.poll_interval_minutes == 5
    assert s.cooldown_minutes == 30


def test_mark_all_read(auth_client, workspace):
    from engine.models import Alert
    for i in range(3):
        Alert.objects.create(workspace=workspace, ticker="AAPL", indicator="PRICE",
                             operator=">", threshold=0.0, metric_value=1.0)
    resp = auth_client.post("/api/v1/alerts/mark-all-read/")
    assert resp.status_code == 200
    assert resp.data == {"updated": 3}
    assert not Alert.objects.filter(workspace=workspace, is_read=False).exists()


def test_healthz_is_public(client):
    resp = client.get("/healthz/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": True, "cache": True}
