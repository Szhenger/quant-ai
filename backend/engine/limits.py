"""Account guards: the strategy cap, and the cost a strategy will incur.

A strategy is a standing order against the evaluation fleet. Its poll
interval fixes how many evaluations it costs per day; with AI enabled, each
evaluation that fires (at most one per cooldown window) costs a paid Claude
call. Both numbers are cheap to compute and worth showing BEFORE deploy —
the same way a brokerage shows buying power before the order, not after.
"""
from __future__ import annotations

import math

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from advisor.budget import calls_today, daily_budget, resets_at

MINUTES_PER_DAY = 24 * 60


def strategy_cap() -> int:
    """Strategies one workspace may hold. 0 = unlimited."""
    return int(getattr(settings, "STRATEGY_MAX_PER_WORKSPACE", 50))


def strategy_count(workspace) -> int:
    return workspace.strategies.count()


def ensure_strategy_capacity(workspace) -> None:
    """Raise a 400 if the workspace is at its cap. Call under the workspace
    row lock (see the views) so two concurrent creates can't both pass."""
    cap = strategy_cap()
    if cap and strategy_count(workspace) >= cap:
        raise ValidationError({
            "non_field_errors": [
                f"This workspace has reached its cap of {cap} strategies. "
                "Delete one to add another."
            ]
        })


def estimate_strategy_cost(poll_interval_minutes: int, cooldown_minutes: int,
                           ai_enabled: bool) -> dict:
    """Upper bounds on what one strategy costs per day.

    * ``evaluations_per_day`` — the sweep enqueues it once per poll interval.
    * ``ai_calls_per_day_max`` — AI runs only when the condition holds AND the
      cooldown has elapsed, so at most one call per cooldown window and never
      more than one per evaluation. 0 when AI is off.
    """
    poll = max(1, int(poll_interval_minutes))
    cooldown = max(1, int(cooldown_minutes))
    evaluations = math.ceil(MINUTES_PER_DAY / poll)
    ai_calls = min(evaluations, math.ceil(MINUTES_PER_DAY / cooldown)) if ai_enabled else 0
    return {"evaluations_per_day": evaluations, "ai_calls_per_day_max": ai_calls}


def account_limits(workspace, user) -> dict:
    """What the console shows next to every deploy button."""
    cap = strategy_cap()
    count = strategy_count(workspace)
    budget = daily_budget()
    used = calls_today(user.id)
    return {
        "strategy_cap": cap,
        "strategy_count": count,
        # None = unlimited; the client treats it as "never at cap".
        "strategies_remaining": max(0, cap - count) if cap else None,
        "ai_daily_budget": budget,
        "ai_calls_today": used,
        "ai_calls_remaining": max(0, budget - used),
        "ai_budget_resets_at": resets_at(timezone.now()),
    }
