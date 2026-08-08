from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.utils import timezone

from strategies.models import Strategy, Alert
from strategies.tasks import evaluate_strategy, sweep_due_strategies, _lock_key

pytestmark = pytest.mark.django_db


def _strategy(workspace, **kwargs):
    defaults = dict(
        workspace=workspace, name="t", ticker="AAPL",
        indicator="PRICE", operator=">", threshold=0.0,
        ai_enabled=False, notify_in_app=True,
    )
    defaults.update(kwargs)
    return Strategy.objects.create(**defaults)


def test_condition_met_creates_alert(workspace):
    # PRICE > 0 always holds for synthetic data.
    s = _strategy(workspace)
    result = evaluate_strategy(str(s.id))
    assert result["status"] == "alerted"
    alert = Alert.objects.get(workspace=workspace)
    assert alert.strategy_id == s.id
    assert alert.ai_used is False
    s.refresh_from_db()
    assert s.last_triggered_at is not None


def test_condition_not_met(workspace):
    s = _strategy(workspace, operator=">", threshold=1e12)
    result = evaluate_strategy(str(s.id))
    assert result["status"] == "quant_not_met"
    assert Alert.objects.count() == 0
    s.refresh_from_db()
    assert s.last_evaluated_at is not None


def test_cooldown_suppresses_second_alert(workspace):
    s = _strategy(workspace, cooldown_minutes=60, last_triggered_at=timezone.now())
    result = evaluate_strategy(str(s.id))
    assert result["status"] == "cooldown"
    assert Alert.objects.count() == 0


def test_evaluate_via_api_action(auth_client, workspace):
    s = _strategy(workspace)
    resp = auth_client.post(f"/api/v1/strategies/{s.id}/evaluate/")
    assert resp.status_code == 200
    assert resp.data["status"] == "alerted"
    # Alert should now be listed
    listing = auth_client.get("/api/v1/alerts/")
    assert listing.data["count"] == 1


def test_ai_disabled_delivery_recorded(workspace):
    s = _strategy(workspace, notify_in_app=True)
    evaluate_strategy(str(s.id))
    alert = Alert.objects.get()
    assert "in_app" in alert.delivery


# --- Composite conditions --------------------------------------------------

def _cmp(indicator, op, right):
    return {"type": "compare", "left": {"indicator": indicator}, "operator": op, "right": right}


def test_composite_and_fires_and_records_audit_detail(workspace):
    # Both branches hold for synthetic data (price is always positive).
    condition = {"type": "group", "op": "AND", "children": [
        _cmp("PRICE", ">", {"value": 0}),
        _cmp("PRICE", ">=", {"value": 0}),
    ]}
    s = _strategy(workspace, condition=condition)
    assert evaluate_strategy(str(s.id))["status"] == "alerted"
    alert = Alert.objects.get(workspace=workspace)
    # The evaluated tree is persisted with the alert as a reproducible audit row.
    assert alert.condition_detail["type"] == "group"
    assert alert.condition_detail["result"] is True
    assert len(alert.condition_detail["children"]) == 2


def test_composite_or_fires_on_a_single_true_branch(workspace):
    condition = {"type": "group", "op": "OR", "children": [
        _cmp("PRICE", ">", {"value": 1e12}),   # false
        _cmp("PRICE", ">", {"value": 0}),       # true
    ]}
    s = _strategy(workspace, condition=condition)
    assert evaluate_strategy(str(s.id))["status"] == "alerted"


def test_alert_owns_up_to_synthetic_data(workspace):
    # Tests run on the synthetic provider, so every alert must be flagged honest.
    s = _strategy(workspace)
    evaluate_strategy(str(s.id))
    alert = Alert.objects.get(workspace=workspace)
    assert alert.data_synthetic is True
    assert alert.message.startswith("[SYNTHETIC DATA]")


def test_composite_and_not_met_creates_no_alert(workspace):
    condition = {"type": "group", "op": "AND", "children": [
        _cmp("PRICE", ">", {"value": 0}),       # true
        _cmp("PRICE", ">", {"value": 1e12}),    # false -> AND fails
    ]}
    s = _strategy(workspace, condition=condition)
    assert evaluate_strategy(str(s.id))["status"] == "quant_not_met"
    assert Alert.objects.count() == 0


# --- Sequential-safety guarantees (S1–S3) ----------------------------------

def test_lock_prevents_concurrent_evaluation(workspace):
    """S1/S3: if the per-strategy lock is already held, evaluation is a no-op —
    no second alert. Simulates a concurrent runner holding the lock."""
    s = _strategy(workspace)  # PRICE > 0 would otherwise alert
    cache.add(_lock_key(str(s.id)), "1", 300)  # pretend another worker holds it
    result = evaluate_strategy(str(s.id))
    assert result["status"] == "locked"
    assert Alert.objects.count() == 0
    # Once released, it evaluates normally and fires exactly one alert.
    cache.delete(_lock_key(str(s.id)))
    assert evaluate_strategy(str(s.id))["status"] == "alerted"
    assert Alert.objects.count() == 1


def test_back_to_back_evaluation_fires_once(workspace):
    """S2: two evaluations in the same cooldown window yield exactly one alert —
    the trigger stamp is committed with the alert, so the second run sees cooldown."""
    s = _strategy(workspace, cooldown_minutes=60)
    assert evaluate_strategy(str(s.id))["status"] == "alerted"
    assert evaluate_strategy(str(s.id))["status"] == "cooldown"
    assert Alert.objects.count() == 1


def test_sweep_claims_each_strategy_once(workspace):
    """S1: two sweep ticks do not enqueue the same due strategy twice — the first
    sweep advances last_evaluated_at (the claim), so the second sees it as not due."""
    _strategy(workspace, poll_interval_minutes=15)  # due (last_evaluated_at is None)
    with patch("strategies.tasks.evaluate_strategy.delay") as delay:
        first = sweep_due_strategies()
        second = sweep_due_strategies()
    assert first["queued"] == 1
    assert second["queued"] == 0
    assert delay.call_count == 1
