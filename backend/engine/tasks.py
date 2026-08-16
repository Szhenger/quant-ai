"""Strategy evaluation fleet.

``sweep_due_strategies`` (Celery Beat, every 60s) finds active strategies whose
poll interval has elapsed and enqueues ``evaluate_strategy`` for each. That task
pulls prices, computes the indicator, checks the condition, optionally asks the
AI to contextualise, and — if it all clears — creates an Alert and delivers it.

Safety / sequential guarantees:
  * ``sweep_due_strategies`` atomically *claims* each due strategy (advances
    ``last_evaluated_at`` at enqueue time) so a later sweep tick cannot enqueue
    the same strategy again while its task is still queued or running.
  * ``evaluate_strategy`` takes a per-strategy lock (shared Redis cache) so it
    never runs concurrently with itself — whether triggered by the scheduler or
    a manual ``/evaluate/`` call. One trigger produces exactly one alert.
  * The alert row and the cooldown stamp are written in a single transaction, so
    a crash can never leave an alert without its ``last_triggered_at`` (which
    would otherwise re-fire on the next evaluation).
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import DurationField, ExpressionWrapper, F, IntegerField, Q
from django.db.models.functions import Cast
from django.utils import timezone

from advisor import ClaudeClient, AlertVerdict
from feeder import (
    get_provider,
    evaluate_condition_tree,
    condition_lookback_days,
    describe_tree,
    primary_metric,
)
from .models import Strategy, Alert
from .delivery import deliver_alert, deliver_alert_channel, notify_strategy_failed

logger = logging.getLogger(__name__)

# Lock lifetime: comfortably longer than one evaluation (price fetch + AI call).
# If a worker dies without releasing, the key expires and evaluation self-heals.
# Must stay ABOVE CELERY_TASK_TIME_LIMIT (settings): the hard time limit kills a
# runaway task before its lock can expire out from under it.
EVAL_LOCK_TTL = 300


def _lock_key(strategy_id: str) -> str:
    return f"quantai:eval-lock:{strategy_id}"


@shared_task(ignore_result=True)
def sweep_due_strategies():
    """Enqueue every due strategy exactly once.

    The due filter runs in the database (per-row poll interval expressed as a
    duration), so a tick's cost scales with the number of DUE strategies, not
    with every active strategy. Each due row is then claimed with the same
    compare-and-set as before, so overlapping sweeps stay duplicate-free.
    """
    now = timezone.now()
    queued = 0
    # Cast: kept for engine portability — SQLite's duration arithmetic rejects
    # PositiveIntegerField operands; on Postgres the cast is a no-op.
    poll_delta = ExpressionWrapper(
        timedelta(minutes=1) * Cast("poll_interval_minutes", output_field=IntegerField()),
        output_field=DurationField(),
    )
    due = (
        Strategy.objects.filter(status=Strategy.Status.ACTIVE)
        .annotate(poll_delta=poll_delta)
        .filter(
            Q(last_evaluated_at__isnull=True)
            | Q(last_evaluated_at__lte=now - F("poll_delta"))
        )
        .values_list("id", "last_evaluated_at")
    )
    for pk, last_eval in due.iterator(chunk_size=500):
        # Atomically claim: only enqueue if THIS row still has the last_evaluated_at
        # we read. A concurrent sweep that already claimed it updates 0 rows here,
        # so the strategy is enqueued exactly once per due window.
        claimed = Strategy.objects.filter(
            pk=pk, last_evaluated_at=last_eval
        ).update(last_evaluated_at=now)
        if claimed:
            try:
                evaluate_strategy.delay(str(pk))
            except Exception:  # noqa: BLE001
                # Broker hiccup after the claim: roll the claim back so the
                # strategy is due again next sweep instead of silently skipping
                # a full poll window (which could be a day).
                logger.exception("Enqueue failed for strategy %s; rolling back claim", pk)
                Strategy.objects.filter(pk=pk, last_evaluated_at=now).update(
                    last_evaluated_at=last_eval
                )
                continue
            queued += 1
    return {"queued": queued}


# acks_late: a worker killed mid-evaluation (OOM, deploy) gets the message
# redelivered instead of losing the run outright. Safe to redeliver — the eval
# lock and the cooldown transaction make the evaluation idempotent.
@shared_task(acks_late=True)
def evaluate_strategy(strategy_id: str):
    """Evaluate one strategy under a per-strategy lock (idempotent w.r.t. itself)."""
    key = _lock_key(strategy_id)
    # cache.add is atomic (Redis SET NX): only one holder at a time, fleet-wide.
    if not cache.add(key, "1", EVAL_LOCK_TTL):
        return {"status": "locked", "strategy_id": strategy_id}
    try:
        return _run_evaluation(strategy_id)
    finally:
        cache.delete(key)


def _persist_eval(strategy: Strategy, value, now):
    """Record a successful evaluation that did NOT fire an alert."""
    strategy.last_metric_value = value
    strategy.last_evaluated_at = now
    strategy.last_error = ""
    strategy.consecutive_failures = 0
    strategy.save(update_fields=[
        "last_metric_value", "last_evaluated_at", "last_error", "consecutive_failures",
    ])




def _run_evaluation(strategy_id: str):
    try:
        strategy = Strategy.objects.get(id=strategy_id)
    except Strategy.DoesNotExist:
        return {"status": "not_found"}

    now = timezone.now()
    try:
        tree = strategy.condition_tree()
        provider = get_provider()
        series = provider.history(strategy.ticker, days=condition_lookback_days(tree))
        outcome = evaluate_condition_tree(tree, series.closes)
        detail = outcome["detail"]
        value = primary_metric(detail)
        data_synthetic = series.synthetic

        if not outcome["result"]:
            _persist_eval(strategy, value, now)
            return {"status": "quant_not_met", "value": value}

        # Respect the cooldown so a persistent condition doesn't spam the user.
        if strategy.last_triggered_at and (now - strategy.last_triggered_at) < timedelta(
            minutes=strategy.cooldown_minutes
        ):
            _persist_eval(strategy, value, now)
            return {"status": "cooldown", "value": value}

        # AI contextualisation (or straight-through when disabled). Network I/O —
        # deliberately outside any DB transaction.
        summary = describe_tree(tree)
        if strategy.ai_enabled:
            news = provider.news(strategy.ticker, limit=5)
            # Synthetic headlines can accompany real prices (or vice versa); the
            # alert is "on synthetic data" if either source was fabricated.
            data_synthetic = data_synthetic or any(n.get("source") == "synthetic" for n in news)
            verdict = ClaudeClient().assess(
                ticker=strategy.ticker,
                condition_summary=summary,
                metric_value=value,
                user_prompt=strategy.ai_prompt,
                news=news,
                data_is_synthetic=data_synthetic,
            )
        else:
            verdict = AlertVerdict(
                trigger=True,
                rationale="Quantitative condition met (AI contextualisation disabled).",
                confidence=1.0,
                ai_used=False,
            )

        if not verdict.trigger:
            _persist_eval(strategy, value, now)
            return {"status": "ai_suppressed", "value": value, "rationale": verdict.rationale}

        value_str = f"{value:.4f}" if value is not None else "n/a"
        prefix = "[SYNTHETIC DATA] " if data_synthetic else ""
        message = f"{prefix}{strategy.ticker}: {summary} (value {value_str}). {verdict.rationale}"

        # S2: create the alert AND stamp the trigger in one transaction, so a crash
        # can never leave an alert without its cooldown stamp. select_for_update is
        # belt-and-suspenders on top of the cache lock (and is exercised for real
        # in tests, which run on PostgreSQL).
        with transaction.atomic():
            locked = Strategy.objects.select_for_update().get(id=strategy_id)
            if locked.last_triggered_at and (now - locked.last_triggered_at) < timedelta(
                minutes=locked.cooldown_minutes
            ):
                _persist_eval(locked, value, now)
                return {"status": "cooldown", "value": value}
            alert = Alert.objects.create(
                workspace=locked.workspace,
                strategy=locked,
                ticker=locked.ticker,
                indicator=locked.indicator,
                operator=locked.operator,
                threshold=locked.threshold,
                metric_value=value,
                ai_used=verdict.ai_used,
                ai_rationale=verdict.rationale,
                ai_confidence=verdict.confidence if verdict.ai_used else None,
                message=message,
                condition_detail=detail,
                data_synthetic=data_synthetic,
            )
            locked.last_triggered_at = now
            locked.last_metric_value = value
            locked.last_evaluated_at = now
            locked.last_error = ""
            locked.consecutive_failures = 0
            locked.save(update_fields=[
                "last_triggered_at", "last_metric_value", "last_evaluated_at",
                "last_error", "consecutive_failures",
            ])

        # Deliver AFTER commit — network I/O must not hold a DB lock/transaction open.
        deliver_alert(alert, locked)
        return {"status": "alerted", "alert_id": str(alert.id), "value": value}

    except Exception as exc:  # noqa: BLE001
        logger.exception("Strategy %s evaluation failed", strategy_id)
        tripped = False
        try:
            limit = int(getattr(settings, "STRATEGY_MAX_CONSECUTIVE_FAILURES", 5))
            strategy.consecutive_failures += 1
            strategy.last_evaluated_at = now
            strategy.last_error = str(exc)[:500]
            fields = ["consecutive_failures", "last_evaluated_at", "last_error"]
            if strategy.consecutive_failures >= limit:
                # Circuit breaker: stop burning fleet capacity on a strategy
                # that keeps failing. The user re-arms it by setting the
                # status back to active (which resets the counter).
                strategy.status = Strategy.Status.FAILED
                fields.append("status")
                tripped = True
            strategy.save(update_fields=fields)
        except Exception:  # noqa: BLE001
            # Best-effort bookkeeping: the evaluation error above is already
            # logged; record (not raise) if even the failure-save failed.
            logger.exception("Could not record failure state for strategy %s", strategy_id)
        return {"status": "error", "error": str(exc)}


# Reconciliation floor: an alert this young may simply still be in the delivery
# queue — re-enqueueing it would guarantee duplicates rather than repair a loss.
RECONCILE_MIN_AGE_MINUTES = 10
# Reconciliation ceiling: bound each pass; older gaps were already retried by
# every earlier pass.
RECONCILE_MAX_AGE_HOURS = 24


@shared_task(ignore_result=True)
def reconcile_undelivered_alerts():
    """Re-enqueue delivery for alerts whose enabled channels never recorded an
    outcome.

    Closes the crash window between an alert's commit and its delivery fan-out:
    without this, a worker death there leaves an alert no channel ever attempts
    (the cooldown is stamped, so it never re-fires either). Runs every 5
    minutes; delivery is thereby at-least-once — receivers dedupe on the alert
    id carried in every payload.
    """
    now = timezone.now()
    window = Alert.objects.filter(
        created_at__lt=now - timedelta(minutes=RECONCILE_MIN_AGE_MINUTES),
        created_at__gte=now - timedelta(hours=RECONCILE_MAX_AGE_HOURS),
    ).select_related("strategy")
    requeued = 0
    for alert in window.iterator(chunk_size=200):
        strategy = alert.strategy
        if strategy is None:
            # Strategy deleted since firing: in-app is the only channel that
            # doesn't depend on strategy config.
            expected = ["in_app"]
        else:
            expected = []
            if strategy.notify_in_app:
                expected.append("in_app")
            if strategy.notify_email:
                expected.append("email")
            if strategy.webhook_url:
                expected.append("webhook")
        recorded = alert.delivery or {}
        for channel in expected:
            if channel not in recorded:
                deliver_alert_channel.delay(str(alert.id), channel)
                requeued += 1
    if requeued:
        logger.warning("Delivery reconciliation re-enqueued %d channel(s)", requeued)


@shared_task(ignore_result=True)
def prune_expired_records():
    """Daily retention: unbounded tables degrade to a stall over months.

    Deletes alerts past ``ALERT_RETENTION_DAYS`` and flushes expired JWTs from
    the blacklist tables (rotation writes one row per refresh, forever).
    """
    cutoff = timezone.now() - timedelta(
        days=int(getattr(settings, "ALERT_RETENTION_DAYS", 180))
    )
    deleted, _ = Alert.objects.filter(created_at__lt=cutoff).delete()
    from django.core.management import call_command

    call_command("flushexpiredtokens")
    logger.info("Retention: pruned %d alert(s) and expired tokens", deleted)
