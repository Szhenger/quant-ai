"""Executable FE<->BE contract pins.

Each test asserts a response shape that frontend/src/api/types.ts declares —
key sets, envelope fields, nullability, auth semantics — so a backend change
that would break the frontend fails CI here instead of in production. Update
types.ts and these pins together, deliberately.
"""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from identity.models import Workspace
from engine.delivery import _payload
from engine.models import Strategy, Alert
from engine.tasks import evaluate_strategy

pytestmark = pytest.mark.django_db

# Mirrors `Strategy` in frontend/src/api/types.ts.
STRATEGY_FIELDS = {
    "id", "name", "ticker", "indicator", "params", "operator", "threshold",
    "condition", "condition_summary",
    "ai_enabled", "ai_prompt", "notify_in_app", "notify_email",
    "webhook_url", "webhook_secret", "status", "poll_interval_minutes",
    "cooldown_minutes", "consecutive_failures", "last_evaluated_at",
    "last_triggered_at", "last_metric_value", "last_error",
    "created_at", "updated_at",
}

# Mirrors `Alert` in frontend/src/api/types.ts.
ALERT_FIELDS = {
    "id", "strategy", "strategy_name", "ticker", "indicator", "operator",
    "threshold", "metric_value", "ai_used", "ai_rationale", "ai_confidence",
    "message", "condition_detail", "data_synthetic", "delivery", "is_read",
    "created_at",
}

# Mirrors `ReplayResult` in frontend/src/api/types.ts.
REPLAY_FIELDS = {
    "strategy_id", "ticker", "condition", "provider", "synthetic",
    "cooldown_bars", "bars", "fire_count", "fires", "dates", "closes",
}

# Mirrors `MarketAnalysis` in frontend/src/api/types.ts.
ANALYSIS_FIELDS = {
    "ticker", "provider", "synthetic", "dates", "closes",
    "latest_price", "indicators",
}

# Mirrors `EvaluateResult.status` in frontend/src/api/types.ts (plus the
# backend-only statuses the union's string fallback covers).
EVALUATE_STATUSES = {
    "alerted", "quant_not_met", "cooldown", "ai_suppressed", "error",
    "locked", "not_found",
    # Non-eager deployments: the evaluation was dispatched to the worker fleet.
    "queued",
}


def _make_strategy(workspace, **kwargs):
    defaults = dict(
        workspace=workspace, name="c", ticker="AAPL",
        indicator="PRICE", operator=">", threshold=0.0, ai_enabled=False,
    )
    defaults.update(kwargs)
    return Strategy.objects.create(**defaults)


def test_paginated_envelope(auth_client):
    resp = auth_client.get("/api/v1/strategies/")
    assert set(resp.data) == {"count", "next", "previous", "results"}


def test_strategy_shape(auth_client):
    resp = auth_client.post("/api/v1/strategies/", {
        "name": "s", "ticker": "AAPL", "indicator": "PRICE",
        "operator": ">", "threshold": 0.0, "ai_enabled": False,
    }, format="json")
    assert resp.status_code == 201, resp.content
    assert set(resp.data) == STRATEGY_FIELDS


def test_strategy_list_omits_the_webhook_secret(auth_client):
    """The signing secret rides on create/detail/rotate only — never on the
    list the console fetches on every page load (types.ts marks it optional)."""
    created = auth_client.post("/api/v1/strategies/", {
        "name": "s", "ticker": "AAPL", "indicator": "PRICE",
        "operator": ">", "threshold": 0.0, "ai_enabled": False,
    }, format="json")
    assert "webhook_secret" in created.data
    listed = auth_client.get("/api/v1/strategies/").data["results"][0]
    assert set(listed) == STRATEGY_FIELDS - {"webhook_secret"}
    detail = auth_client.get(f"/api/v1/strategies/{created.data['id']}/").data
    assert detail["webhook_secret"] == created.data["webhook_secret"]


def test_alert_shape_and_nullability(auth_client, workspace):
    s = _make_strategy(workspace)
    evaluate_strategy(str(s.id))
    resp = auth_client.get("/api/v1/alerts/")
    row = resp.data["results"][0]
    assert set(row) == ALERT_FIELDS
    assert row["metric_value"] is None or isinstance(row["metric_value"], float)
    assert isinstance(row["delivery"], dict)


def test_ws_alert_payload_matches_rest_alert_shape(workspace):
    # The WebSocket frame carries the same serialized alert as the REST list.
    s = _make_strategy(workspace)
    evaluate_strategy(str(s.id))
    assert set(_payload(Alert.objects.get())) == ALERT_FIELDS


def test_replay_shape(auth_client, workspace):
    s = _make_strategy(workspace)
    resp = auth_client.post(f"/api/v1/strategies/{s.id}/replay/", {"days": 30},
                            format="json")
    assert set(resp.data) == REPLAY_FIELDS
    assert set(resp.data["fires"][0]) == {"index", "date", "metric"}


def test_market_analysis_shape(auth_client):
    resp = auth_client.get("/api/v1/markets/AAPL/analysis/")
    assert set(resp.data) == ANALYSIS_FIELDS
    for value in resp.data["indicators"].values():
        if value is not None:
            assert set(value) == {"label", "unit", "value", "params"}


def test_indicator_catalog_shape(auth_client):
    resp = auth_client.get("/api/v1/indicators/")
    assert set(resp.data) == {"indicators", "operators"}
    assert set(resp.data["indicators"][0]) == {
        "key", "label", "unit", "defaults", "default_threshold", "help",
        "summary", "readings",
    }
    # Reading bands use the strategy operator vocabulary minus the crosses.
    for entry in resp.data["indicators"]:
        for band in entry["readings"]:
            assert "text" in band
            if "op" in band:
                assert band["op"] in {"<", ">", "<=", ">="} and "at" in band
    assert set(resp.data["operators"][0]) == {"key", "label"}


def test_evaluate_status_vocabulary(auth_client, workspace):
    s = _make_strategy(workspace)
    resp = auth_client.post(f"/api/v1/strategies/{s.id}/evaluate/")
    assert resp.data["status"] in EVALUATE_STATUSES


def test_token_refresh_rotates_and_blacklists(user):
    """The refresh endpoint returns BOTH tokens and kills the submitted one —
    the client MUST persist the rotated refresh token (types.ts AuthTokens)."""
    api = APIClient()
    resp = api.post("/api/v1/auth/token/", {
        "username": "trader", "password": "pw12345!",
    }, format="json")
    old_refresh = resp.data["refresh"]

    rotated = api.post("/api/v1/auth/token/refresh/", {"refresh": old_refresh},
                       format="json")
    assert rotated.status_code == 200
    assert set(rotated.data) == {"access", "refresh"}
    assert rotated.data["refresh"] != old_refresh

    reused = api.post("/api/v1/auth/token/refresh/", {"refresh": old_refresh},
                      format="json")
    assert reused.status_code == 401  # blacklisted after rotation


def test_logout_blacklists_refresh_token(user):
    """POST /auth/logout/ revokes the refresh token server-side — after it,
    the token the client held must stop refreshing (types.ts AuthTokens).
    No Authorization header: possession of the refresh token is the credential
    (the client may be logging out with an already-expired access token)."""
    resp = APIClient().post("/api/v1/auth/token/", {
        "username": "trader", "password": "pw12345!",
    }, format="json")
    refresh = resp.data["refresh"]

    out = APIClient().post("/api/v1/auth/logout/", {"refresh": refresh},
                           format="json")
    assert out.status_code == 205

    reused = APIClient().post("/api/v1/auth/token/refresh/", {"refresh": refresh},
                              format="json")
    assert reused.status_code == 401


def test_workspace_scoping_error_codes(auth_client):
    """403 = header missing; 404 = workspace not owned. The client can rely on
    the distinction (e.g. to trigger workspace re-selection)."""
    other = get_user_model().objects.create_user(username="intruder", password="pw!")
    other_ws = Workspace.objects.create(name="theirs", owner=other)
    auth_client.defaults["HTTP_X_WORKSPACE_ID"] = str(other_ws.id)
    assert auth_client.get("/api/v1/strategies/").status_code == 404
    del auth_client.defaults["HTTP_X_WORKSPACE_ID"]
    assert auth_client.get("/api/v1/strategies/").status_code == 403
