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
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from ai import ClaudeClient, AlertVerdict
from marketdata import (
    get_provider,
    evaluate_condition_tree,
    condition_lookback_days,
    describe_tree,
    primary_metric,
)
from .models import Strategy, Alert
from .delivery import deliver_alert

logger = logging.getLogger(__name__)

# Lock lifetime: comfortably longer than one evaluation (price fetch + AI call).
# If a worker dies without releasing, the key expires and evaluation self-heals.
EVAL_LOCK_TTL = 300


def _lock_key(strategy_id: str) -> str:
    return f"quantai:eval-lock:{strategy_id}"


@shared_task
def sweep_due_strategies():
    now = timezone.now()
    queued = 0
    active = Strategy.objects.filter(status=Strategy.Status.ACTIVE).only(
        "id", "last_evaluated_at", "poll_interval_minutes"
    )
    for strategy in active:
        due = (
            strategy.last_evaluated_at is None
            or (now - strategy.last_evaluated_at) >= timedelta(minutes=strategy.poll_interval_minutes)
        )
        if not due:
            continue
        # Atomically claim: only enqueue if THIS row still has the last_evaluated_at
        # we read. A concurrent sweep that already claimed it updates 0 rows here,
        # so the strategy is enqueued exactly once per due window.
        claimed = Strategy.objects.filter(
            pk=strategy.pk, last_evaluated_at=strategy.last_evaluated_at
        ).update(last_evaluated_at=now)
        if claimed:
            evaluate_strategy.delay(str(strategy.pk))
            queued += 1
    return {"queued": queued}


@shared_task
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


def _persist_eval(strategy: Strategy, value, now, error: str = ""):
    """Record an evaluation that did NOT fire an alert."""
    strategy.last_metric_value = value
    strategy.last_evaluated_at = now
    strategy.last_error = error
    strategy.save(update_fields=["last_metric_value", "last_evaluated_at", "last_error"])




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
        # belt-and-suspenders on top of the cache lock (a no-op on sqlite in tests).
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
                metric_value=value if value is not None else 0.0,
                ai_used=verdict.ai_used,
                ai_rationale=verdict.rationale,
                message=message,
                condition_detail=detail,
                data_synthetic=data_synthetic,
            )
            locked.last_triggered_at = now
            locked.last_metric_value = value
            locked.last_evaluated_at = now
            locked.last_error = ""
            locked.save(update_fields=[
                "last_triggered_at", "last_metric_value", "last_evaluated_at", "last_error",
            ])

        # Deliver AFTER commit — network I/O must not hold a DB lock/transaction open.
        deliver_alert(alert, locked)
        return {"status": "alerted", "alert_id": str(alert.id), "value": value}

    except Exception as exc:  # noqa: BLE001
        logger.exception("Strategy %s evaluation failed", strategy_id)
        try:
            _persist_eval(strategy, strategy.last_metric_value, now, error=str(exc)[:500])
        except Exception:  # noqa: BLE001
            pass
        return {"status": "error", "error": str(exc)}
