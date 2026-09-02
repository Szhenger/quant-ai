"""Account guards: the per-workspace strategy cap, the per-user daily AI
budget (fail-open), and the cost estimate every strategy carries."""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import override_settings

from advisor import budget
from advisor.claude_client import ClaudeClient
from identity.limits import estimate_strategy_cost
from strategies.models import Strategy

pytestmark = pytest.mark.django_db

_SIMPLE = {"name": "t", "ticker": "AAPL", "indicator": "PRICE", "operator": ">",
           "threshold": 0, "ai_enabled": False}
_GRAPH = {
    "name": "g",
    "nodes": [
        {"id": "a", "type": "asset", "data": {"ticker": "AAPL"}},
        {"id": "q", "type": "quant", "data": {"indicator": "PRICE", "operator": ">", "value": 0}},
    ],
    "edges": [{"source": "a", "target": "q"}],
}


# --- Strategy cap -------------------------------------------------------------

@override_settings(STRATEGY_MAX_PER_WORKSPACE=2)
def test_workspace_strategy_cap_is_enforced_on_both_builders(auth_client):
    assert auth_client.post("/api/v1/strategies/", _SIMPLE, format="json").status_code == 201
    assert auth_client.post("/api/v1/strategies/deploy-graph/", _GRAPH, format="json").status_code == 201
    third = auth_client.post("/api/v1/strategies/", _SIMPLE, format="json")
    assert third.status_code == 400
    assert "cap of 2" in json.dumps(third.data)
    graph = auth_client.post("/api/v1/strategies/deploy-graph/", _GRAPH, format="json")
    assert graph.status_code == 400
    assert Strategy.objects.count() == 2


@override_settings(STRATEGY_MAX_PER_WORKSPACE=1)
def test_cap_counts_paused_strategies_and_frees_on_delete(auth_client):
    created = auth_client.post("/api/v1/strategies/", _SIMPLE, format="json").data
    auth_client.patch(f"/api/v1/strategies/{created['id']}/", {"status": "paused"}, format="json")
    assert auth_client.post("/api/v1/strategies/", _SIMPLE, format="json").status_code == 400
    auth_client.delete(f"/api/v1/strategies/{created['id']}/")
    assert auth_client.post("/api/v1/strategies/", _SIMPLE, format="json").status_code == 201


@override_settings(STRATEGY_MAX_PER_WORKSPACE=0)
def test_zero_cap_means_unlimited(auth_client):
    for _ in range(3):
        assert auth_client.post("/api/v1/strategies/", _SIMPLE, format="json").status_code == 201
    assert auth_client.get("/api/v1/limits/").data["strategies_remaining"] is None


# --- Cost estimate ------------------------------------------------------------

def test_cost_estimate_bounds():
    assert estimate_strategy_cost(15, 60, False) == {
        "evaluations_per_day": 96, "ai_calls_per_day_max": 0,
    }
    # AI runs at most once per cooldown window, never more than once per evaluation.
    assert estimate_strategy_cost(15, 60, True)["ai_calls_per_day_max"] == 24
    assert estimate_strategy_cost(60, 15, True)["ai_calls_per_day_max"] == 24
    assert estimate_strategy_cost(1, 1440, True)["ai_calls_per_day_max"] == 1
    # Non-dividing intervals round up ("up to").
    assert estimate_strategy_cost(7, 1440, False)["evaluations_per_day"] == 206


def test_every_strategy_carries_its_cost_estimate(auth_client):
    created = auth_client.post("/api/v1/strategies/", {
        **_SIMPLE, "ai_enabled": True, "poll_interval_minutes": 30, "cooldown_minutes": 120,
    }, format="json").data
    assert created["cost_estimate"] == {"evaluations_per_day": 48, "ai_calls_per_day_max": 12}
    listed = auth_client.get("/api/v1/strategies/").data["results"][0]
    assert listed["cost_estimate"] == created["cost_estimate"]


# --- AI daily budget ----------------------------------------------------------

@override_settings(AI_DAILY_CALL_BUDGET=2)
def test_reserve_call_is_a_counter_per_user_per_day(user):
    assert budget.calls_today(user.id) == 0
    assert budget.reserve_call(user.id) is True
    assert budget.reserve_call(user.id) is True
    assert budget.reserve_call(user.id) is False  # third call: over budget
    assert budget.calls_today(user.id) == 3  # attempts are recorded, not clipped
    assert budget.reserve_call(user.id + 1) is True  # another user, own counter
    assert budget.reserve_call(None) is True  # ungated caller


def _fake_anthropic(verdict: dict):
    """A stand-in for the SDK: records whether the paid call was made."""
    calls = []

    class _Client:
        def __init__(self, **kw):
            pass

        class messages:  # noqa: N801 — mirrors client.messages.create
            @staticmethod
            def create(**kw):
                calls.append(kw)
                return SimpleNamespace(
                    stop_reason="end_turn",
                    content=[SimpleNamespace(type="text", text=json.dumps(verdict))],
                )

    return SimpleNamespace(Anthropic=_Client), calls


@override_settings(AI_DAILY_CALL_BUDGET=1)
def test_assess_fails_open_once_the_budget_is_spent(user):
    fake, calls = _fake_anthropic({"trigger_alert": False, "rationale": "noise", "confidence": 0.9})
    client = ClaudeClient(api_key="test-key", user_id=user.id)
    kwargs = dict(ticker="AAPL", condition_summary="PRICE > 0", metric_value=1.0, user_prompt="")
    with patch.dict("sys.modules", {"anthropic": fake}):
        first = client.assess(**kwargs)
        second = client.assess(**kwargs)
    # Within budget: the paid call ran and its verdict (suppress) was honoured.
    assert first.ai_used is True and first.trigger is False
    # Over budget: no paid call, and the alert fires on the quant condition.
    assert len(calls) == 1
    assert second.ai_used is False and second.trigger is True
    assert "budget exhausted" in second.rationale
    assert second.confidence == 0.5


@override_settings(AI_DAILY_CALL_BUDGET=0)
def test_news_summary_falls_back_when_budget_is_spent(user):
    fake, calls = _fake_anthropic({})
    client = ClaudeClient(api_key="test-key", user_id=user.id)
    with patch.dict("sys.modules", {"anthropic": fake}):
        out = client.summarize_news(ticker="AAPL", news=[{"title": "x", "source": "y"}])
    assert calls == []
    assert out.source == "fallback"


def test_disabled_client_never_spends_budget(user):
    client = ClaudeClient(api_key="", user_id=user.id)
    client.assess(ticker="AAPL", condition_summary="PRICE > 0", metric_value=1.0, user_prompt="")
    client.summarize_news(ticker="AAPL", news=[{"title": "x", "source": "y"}])
    assert budget.calls_today(user.id) == 0


# --- The limits endpoint ------------------------------------------------------

@override_settings(STRATEGY_MAX_PER_WORKSPACE=5, AI_DAILY_CALL_BUDGET=10)
def test_limits_endpoint_reports_usage(auth_client, user):
    auth_client.post("/api/v1/strategies/", _SIMPLE, format="json")
    budget.reserve_call(user.id)
    budget.reserve_call(user.id)
    data = auth_client.get("/api/v1/limits/").data
    assert data["strategy_cap"] == 5 and data["strategy_count"] == 1
    assert data["strategies_remaining"] == 4
    assert data["ai_daily_budget"] == 10 and data["ai_calls_today"] == 2
    assert data["ai_calls_remaining"] == 8
    assert data["ai_budget_resets_at"] is not None
