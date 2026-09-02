"""Per-user daily budget for paid AI calls.

Every Claude call in the system (alert contextualisation, stock-page news
summaries) is billed against the operator's API key, and every one of them is
triggered by something a user configured: N strategies × short polls × AI on,
or a watchlist of many tickers on a short refresh cadence. Without a ceiling
that is a cost-amplification vector one account can pull on indefinitely.

The budget is a counter per (user, UTC day) in the shared cache: ``reserve``
is an atomic increment-and-compare, so concurrent workers can't both squeeze
through the last slot. Exhaustion is *fail-open* — the caller falls back to
its no-AI path exactly as it does when the API is down — so a spent budget
never suppresses a quantitative alert, it only stops paying for context.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.core.cache import cache

# Two days: the key must outlive its own UTC day so a late reader (the limits
# endpoint at 23:59) still sees today's count; it is never read after that.
_KEY_TTL = 2 * 24 * 3600


def daily_budget() -> int:
    return int(settings.AI_DAILY_CALL_BUDGET)


def _today() -> datetime:
    return datetime.now(timezone.utc)


def budget_key(user_id, day: datetime | None = None) -> str:
    day = day or _today()
    return f"quantai:ai-budget:{user_id}:{day:%Y-%m-%d}"


def resets_at(now: datetime | None = None) -> datetime:
    """Next UTC midnight — when the counter starts from zero again."""
    now = now or _today()
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def calls_today(user_id) -> int:
    return int(cache.get(budget_key(user_id), 0) or 0)


def reserve_call(user_id) -> bool:
    """Claim one AI call for this user today. False when the budget is spent.

    ``add`` then ``incr`` is atomic on Redis (SET NX + INCR) and on LocMem;
    the count records attempts, so an over-budget call still increments — the
    limits endpoint can then show "220 attempted of 200" rather than pinning
    at the cap and hiding the overrun.
    """
    if user_id is None:
        return True  # no owner to bill: legacy/internal caller, never gated
    key = budget_key(user_id)
    cache.add(key, 0, _KEY_TTL)
    try:
        used = cache.incr(key)
    except ValueError:
        # The key expired between add and incr (day rollover): start fresh.
        cache.add(key, 0, _KEY_TTL)
        used = cache.incr(key)
    return used <= daily_budget()
