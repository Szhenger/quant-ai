"""Known bugs, pinned as xfail regression tests.

Each test encodes the DESIRED behavior for a defect found in the 2026-08 code
audit (see test/README.md → "Known bugs"). They are marked ``xfail`` (non-
strict) so the suite stays green today; when a fix lands, the test flips to
XPASS in the report — remove the marker in the same PR to lock the fix in.
"""
from types import SimpleNamespace

import pytest

from engine import tasks
from engine.compiler import GraphCompilationError, compile_graph
from engine.models import Strategy
from feeder.indicators import compute_indicator

pytestmark = pytest.mark.django_db


def _strategy(workspace, **overrides):
    fields = dict(
        workspace=workspace, name="Buggy", ticker="AAPL",
        indicator="PRICE", operator=">", threshold=0.0, ai_enabled=False,
    )
    fields.update(overrides)
    return Strategy.objects.create(**fields)


@pytest.mark.xfail(reason="AUDIT-B1: notify_strategy_failed is imported but never "
                          "called — the breaker trips silently", strict=False)
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
    assert strategy.status == Strategy.Status.FAILED  # this part works today
    assert notified == [strategy.pk], (
        "a strategy that will never be swept again must tell its owner"
    )


@pytest.mark.xfail(reason="AUDIT-B6: with an AI node present, conditions not wired "
                          "into the tree are silently dropped", strict=False)
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
    with pytest.raises(GraphCompilationError):
        compile_graph(nodes, edges)


@pytest.mark.xfail(reason="AUDIT-B7: MACD histogram unmasks from index `slow`, "
                          "before its own n >= slow+signal warm-up standard",
                   strict=False)
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


@pytest.mark.xfail(reason="AUDIT-B4: PATCHing flat fields on a composite strategy "
                          "returns 200 but silently discards the change",
                   strict=False)
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
    # Desired: either the edit is applied to the tree's representative leaf, or
    # the request is rejected — never a 200 that changed nothing.
    assert (response.status_code == 400
            or response.json()["threshold"] == 25.0), (
        f"200 with threshold={response.json().get('threshold')} — the user "
        f"believes they tightened a rule that did not change"
    )


@pytest.mark.xfail(reason="AUDIT-B2: reconciliation derives expected channels from "
                          "the strategy's CURRENT flags, not its fire-time flags",
                   strict=False)
def test_enabling_a_channel_does_not_backfill_deliveries_for_old_alerts(
        workspace, monkeypatch):
    from datetime import timedelta

    from django.utils import timezone

    from engine.models import Alert

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
