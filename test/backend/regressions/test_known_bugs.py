"""Regression locks for the defects found in the 2026-08 code audit.

Each test encodes the DESIRED behavior for a bug found in the audit (see
test/README.md → "Known bugs"). They started life as non-strict ``xfail``
pins; the fixes have landed, so the markers are gone and these now guard the
fixed behavior permanently.
"""
from types import SimpleNamespace

import pytest

from strategies import tasks
from strategies.compiler import GraphCompilationError, compile_graph
from strategies.models import Strategy
from markets.indicators import compute_indicator

pytestmark = pytest.mark.django_db


def _strategy(workspace, **overrides):
    fields = dict(
        workspace=workspace, name="Buggy", ticker="AAPL",
        indicator="PRICE", operator=">", threshold=0.0, ai_enabled=False,
    )
    fields.update(overrides)
    return Strategy.objects.create(**fields)


# AUDIT-B1: the breaker used to trip silently — notify_strategy_failed was
# imported but never called.
def test_tripping_the_circuit_breaker_notifies_the_owner(workspace, monkeypatch, settings):
    settings.STRATEGY_MAX_CONSECUTIVE_FAILURES = 1
    strategy = _strategy(workspace)
    notified = []
    monkeypatch.setattr(tasks, "notify_strategy_failed",
                        lambda s: notified.append(s.pk))

    def broken_provider():
        raise RuntimeError("provider down")

    monkeypatch.setattr(tasks, "get_provider", broken_provider)
    tasks.evaluate_strategy(str(strategy.pk))

    strategy.refresh_from_db()
    assert strategy.status == Strategy.Status.FAILED
    assert notified == [strategy.pk], (
        "a strategy that will never be swept again must tell its owner"
    )


# AUDIT-B3 (companion to B1): failure bookkeeping is a conditional update on
# ACTIVE rows only — it must never revert a concurrent user pause/re-arm.
def test_failure_bookkeeping_never_overwrites_a_concurrent_pause(workspace, monkeypatch):
    strategy = _strategy(workspace)

    def failing_provider_that_races_a_pause():
        # The user pauses the strategy while the evaluation is mid-flight.
        Strategy.objects.filter(pk=strategy.pk).update(status=Strategy.Status.PAUSED)
        raise RuntimeError("provider down")

    monkeypatch.setattr(tasks, "get_provider", failing_provider_that_races_a_pause)
    tasks.evaluate_strategy(str(strategy.pk))

    strategy.refresh_from_db()
    assert strategy.status == Strategy.Status.PAUSED  # the user's action wins
    assert strategy.consecutive_failures == 0


# AUDIT-B6: with an AI node present, conditions not wired into the tree used
# to be silently dropped.
def test_graph_compiler_rejects_conditions_left_out_of_the_tree():
    nodes = [
        {"id": "asset", "type": "asset", "data": {"ticker": "AAPL"}},
        {"id": "wired", "type": "quant",
         "data": {"indicator": "RSI", "operator": "<", "value": 30.0}},
        {"id": "orphan", "type": "quant",
         "data": {"indicator": "VOLATILITY", "operator": ">", "value": 60.0}},
        {"id": "ai", "type": "ai", "data": {"prompt": ""}},
    ]
    edges = [
        {"source": "asset", "target": "wired"},
        {"source": "wired", "target": "ai"},
        # "orphan" feeds nothing — the user thinks it gates the alert.
    ]
    with pytest.raises(GraphCompilationError, match="orphan"):
        compile_graph(nodes, edges)


# AUDIT-B7: the MACD histogram used to unmask values before its own
# n >= slow+signal warm-up standard.
def test_macd_histogram_masks_the_full_warmup_region():
    fast, slow, signal = 12, 26, 9
    closes = [100.0 + (i % 7) for i in range(40)]
    series = compute_indicator(
        "MACD_HIST", closes, {"fast": fast, "slow": slow, "signal": signal}
    )["series"]
    warmup = series[: slow + signal - 1]
    assert all(v is None for v in warmup), (
        "histogram values exposed while the signal-line EMA is still warming up"
    )
    assert series[slow + signal - 1] is not None  # and no over-masking


# AUDIT-B4: PATCHing a flat field on a composite strategy used to return 200
# while silently discarding the change.
def test_patching_a_flat_field_on_a_composite_strategy_is_not_silently_dropped(
        auth_client, workspace):
    created = auth_client.post("/api/v1/strategies/", {
        "name": "Composite", "ticker": "AAPL",
        "indicator": "RSI", "operator": "<", "threshold": 30.0,
        "ai_enabled": False,
        "condition": {
            "type": "compare",
            "left": {"indicator": "RSI", "params": {"period": 14}},
            "operator": "<",
            "right": {"value": 30.0},
        },
    }, format="json")
    assert created.status_code == 201, created.content

    response = auth_client.patch(
        f"/api/v1/strategies/{created.json()['id']}/",
        {"threshold": 25.0}, format="json",
    )
    assert response.status_code == 400
    assert "threshold" in response.json()  # the error names the offending field

    # Editing non-derived fields (pause, cooldown, delivery) still works.
    response = auth_client.patch(
        f"/api/v1/strategies/{created.json()['id']}/",
        {"status": "paused"}, format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "paused"


# AUDIT-B2: reconciliation used to derive expected channels from the
# strategy's CURRENT flags; it now works off the alert's fire-time snapshot.
def test_enabling_a_channel_does_not_backfill_deliveries_for_old_alerts(
        workspace, monkeypatch):
    from datetime import timedelta

    from django.utils import timezone

    from strategies.models import Alert

    strategy = _strategy(workspace, notify_in_app=True, notify_email=False)
    alert = Alert.objects.create(
        workspace=workspace, strategy=strategy, ticker="AAPL",
        indicator="PRICE", operator=">", threshold=0.0,
        delivery={"in_app": {"ok": True}},  # fully delivered at fire time
    )
    Alert.objects.filter(pk=alert.pk).update(
        created_at=timezone.now() - timedelta(hours=3)
    )
    # Hours later the user turns on email for FUTURE alerts…
    strategy.notify_email = True
    strategy.save(update_fields=["notify_email"])

    requeued = []
    monkeypatch.setattr(
        tasks, "deliver_alert_channel",
        SimpleNamespace(delay=lambda alert_id, channel: requeued.append(channel)),
    )
    tasks.reconcile_undelivered_alerts()
    assert requeued == [], "hours-old alerts must not be re-delivered as fresh"


# AUDIT-B5: a redelivered task that finds the (possibly orphaned) eval lock
# held must requeue itself for after the TTL instead of dropping the run.
def test_lock_contention_requeues_once_instead_of_dropping_the_run(workspace, monkeypatch):
    from django.core.cache import cache

    from strategies.tasks import EVAL_LOCK_TTL, _lock_key

    strategy = _strategy(workspace)
    cache.add(_lock_key(str(strategy.pk)), "1", EVAL_LOCK_TTL)  # orphaned lock

    requeues = []
    monkeypatch.setattr(
        tasks.evaluate_strategy, "apply_async",
        lambda *a, **kw: requeues.append((kw.get("args"), kw.get("kwargs"), kw.get("countdown"))),
    )
    result = tasks.evaluate_strategy(str(strategy.pk))
    assert result["status"] == "locked"
    assert requeues == [((str(strategy.pk),), {"rescheduled": True}, EVAL_LOCK_TTL)]

    # The requeued run must NOT requeue again — one deferral, then give up to
    # the next sweep (no infinite chains).
    requeues.clear()
    result = tasks.evaluate_strategy(str(strategy.pk), rescheduled=True)
    assert result["status"] == "locked"
    assert requeues == []
