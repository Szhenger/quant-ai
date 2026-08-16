"""Celery / Redis fleet behavior.

Tasks run eagerly here (config/test_settings.py), so what's under test is the
task *logic* and the configuration invariants the fleet's safety story rests
on — the lock-vs-time-limit ordering, JSON-only serialization, the beat
schedule pointing at real tasks, and the claim/reconcile/prune loops.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from celery import current_app
from django.conf import settings
from django.utils import timezone
from django.utils.module_loading import import_string

from engine import tasks
from engine.models import Alert, Strategy
from engine.tasks import EVAL_LOCK_TTL

pytestmark = pytest.mark.django_db


def _strategy(workspace, **overrides):
    fields = dict(
        workspace=workspace, name="Sweep me", ticker="AAPL",
        indicator="PRICE", operator=">", threshold=0.0, ai_enabled=False,
    )
    fields.update(overrides)
    return Strategy.objects.create(**fields)


def _alert(workspace, strategy, age_minutes, delivery=None):
    alert = Alert.objects.create(
        workspace=workspace, strategy=strategy, ticker="AAPL",
        indicator="PRICE", operator=">", threshold=0.0,
        delivery=delivery or {},
    )
    # created_at is auto_now_add; backdate it through the ORM update path.
    Alert.objects.filter(pk=alert.pk).update(
        created_at=timezone.now() - timedelta(minutes=age_minutes)
    )
    alert.refresh_from_db()
    return alert


# --------------------------------------------------------------------------- #
# Configuration invariants
# --------------------------------------------------------------------------- #
def test_beat_schedule_entries_point_at_real_registered_tasks():
    for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
        task = import_string(entry["task"])
        assert hasattr(task, "delay"), f"{name} does not reference a Celery task"
        assert entry["schedule"] > 0, name


def test_sweep_runs_at_least_once_per_minimum_poll_interval():
    """A strategy can ask for a 1-minute poll; the sweep must tick that fast."""
    sweep = settings.CELERY_BEAT_SCHEDULE["sweep-due-strategies-every-minute"]
    assert sweep["schedule"] <= 60.0


def test_eval_lock_outlives_the_hard_task_time_limit():
    """The documented ordering: a runaway task is killed (TIME_LIMIT) before its
    per-strategy lock can expire out from under it (EVAL_LOCK_TTL)."""
    assert EVAL_LOCK_TTL > settings.CELERY_TASK_TIME_LIMIT
    assert settings.CELERY_TASK_SOFT_TIME_LIMIT < settings.CELERY_TASK_TIME_LIMIT


def test_celery_speaks_json_only():
    """Pickle in the broker is remote code execution waiting for a Redis
    compromise; the fleet must accept and emit JSON only."""
    assert settings.CELERY_ACCEPT_CONTENT == ["json"]
    assert settings.CELERY_TASK_SERIALIZER == "json"
    assert settings.CELERY_RESULT_SERIALIZER == "json"


def test_results_expire_well_before_a_day():
    """One sweep result per minute accrues forever on a small noeviction Redis
    unless results expire promptly."""
    assert settings.CELERY_RESULT_EXPIRES <= 6 * 3600


def test_eager_mode_is_on_in_tests_and_propagates():
    assert current_app.conf.task_always_eager
    assert current_app.conf.task_eager_propagates


# --------------------------------------------------------------------------- #
# The sweep's claim protocol
# --------------------------------------------------------------------------- #
def test_sweep_claim_rolls_back_when_the_broker_enqueue_fails(workspace, monkeypatch):
    strategy = _strategy(workspace)  # never evaluated → due now
    original = strategy.last_evaluated_at

    def boom(*args, **kwargs):
        raise ConnectionError("broker down")

    monkeypatch.setattr(tasks, "evaluate_strategy", SimpleNamespace(delay=boom))
    result = tasks.sweep_due_strategies()

    strategy.refresh_from_db()
    assert result == {"queued": 0}
    # The claim must be rolled back, or the strategy silently skips a full
    # poll window (which can be a day) every time the broker hiccups.
    assert strategy.last_evaluated_at == original


def test_sweep_enqueues_a_due_strategy_exactly_once(workspace, monkeypatch):
    _strategy(workspace)
    calls = []
    monkeypatch.setattr(
        tasks, "evaluate_strategy",
        SimpleNamespace(delay=lambda pk: calls.append(pk)),
    )
    assert tasks.sweep_due_strategies() == {"queued": 1}
    # The claim advanced last_evaluated_at, so an immediately-following sweep
    # (an overlapping beat tick) finds nothing to do.
    assert tasks.sweep_due_strategies() == {"queued": 0}
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# Delivery reconciliation (the crash-window repair loop)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def requeued(monkeypatch):
    calls = []
    monkeypatch.setattr(
        tasks, "deliver_alert_channel",
        SimpleNamespace(delay=lambda alert_id, channel: calls.append((alert_id, channel))),
    )
    return calls


def test_reconcile_requeues_only_channels_with_no_recorded_outcome(workspace, requeued):
    strategy = _strategy(workspace, notify_in_app=True, notify_email=True)
    alert = _alert(workspace, strategy, age_minutes=30,
                   delivery={"in_app": {"ok": True}})
    tasks.reconcile_undelivered_alerts()
    assert requeued == [(str(alert.id), "email")]


def test_reconcile_leaves_young_alerts_alone(workspace, requeued):
    """An alert younger than the floor may still be sitting in the delivery
    queue — re-enqueueing it would guarantee duplicates."""
    _alert(workspace, _strategy(workspace), age_minutes=1)
    tasks.reconcile_undelivered_alerts()
    assert requeued == []


def test_reconcile_ignores_alerts_past_the_repair_ceiling(workspace, requeued):
    _alert(workspace, _strategy(workspace), age_minutes=60 * 25)
    tasks.reconcile_undelivered_alerts()
    assert requeued == []


def test_reconcile_for_a_deleted_strategy_expects_in_app_only(workspace, requeued):
    alert = _alert(workspace, None, age_minutes=30)
    tasks.reconcile_undelivered_alerts()
    assert requeued == [(str(alert.id), "in_app")]


def test_reconcile_is_idempotent_once_outcomes_are_recorded(workspace, requeued):
    _alert(workspace, _strategy(workspace), age_minutes=30,
           delivery={"in_app": {"ok": True}})
    tasks.reconcile_undelivered_alerts()
    assert requeued == []


# --------------------------------------------------------------------------- #
# Retention
# --------------------------------------------------------------------------- #
def test_prune_deletes_only_alerts_past_retention(workspace, settings):
    settings.ALERT_RETENTION_DAYS = 30
    strategy = _strategy(workspace)
    old = _alert(workspace, strategy, age_minutes=60 * 24 * 31)
    fresh = _alert(workspace, strategy, age_minutes=60)
    tasks.prune_expired_records()
    remaining = set(Alert.objects.values_list("id", flat=True))
    assert fresh.id in remaining
    assert old.id not in remaining


# --------------------------------------------------------------------------- #
# Eager execution sanity
# --------------------------------------------------------------------------- #
def test_evaluate_strategy_runs_inline_and_returns_a_json_safe_dict():
    result = tasks.evaluate_strategy.delay("00000000-0000-0000-0000-000000000000")
    assert result.get() == {"status": "not_found"}
