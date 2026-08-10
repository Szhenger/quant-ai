"""Fleet-wide shared bar cache with single-flight fetch coalescing.

The "market-data service" layer: one fetch path serving strategy evaluation,
signal replay and market analysis. Bars are cached in the shared Django cache
(Redis in production), so N strategies on the same ticker cost ONE upstream
fetch per TTL window across the whole worker fleet — and a single-flight lock
makes concurrent cache misses for the same ticker coalesce onto one fetch
instead of stampeding the provider.

Requests are fetched in bucket-sized windows (multiples of ``DAYS_BUCKET``) so
different lookbacks on the same ticker (120, 180, ...) collapse into one cache
entry, then trimmed to the requested length on the way out.

Honesty contract: the ``PriceSeries`` is cached verbatim INCLUDING its
``synthetic`` flag, so degraded fallback data is never laundered into real data
by this cache. Synthetic results are cached only briefly (``synthetic_ttl``) so
a transient provider failure doesn't pin fallback data for the full TTL.

A cache outage must never break the pipeline: every cache operation degrades to
"just fetch upstream" on error.
"""
from __future__ import annotations

import logging
import math
import time

from django.conf import settings
from django.core.cache import cache

from .providers import BaseProvider, PriceSeries

logger = logging.getLogger(__name__)

# Fetch windows are rounded up to multiples of this many trading days.
DAYS_BUCKET = 180

# Single-flight lock lifetime: comfortably above one upstream fetch (yfinance
# runs with an explicit 20s timeout). If the fetcher dies, the lock expires and
# the next caller takes over.
FETCH_LOCK_TTL = 60

# Poll cadence for waiters coalescing on another worker's in-flight fetch.
_WAIT_STEP_SECONDS = 0.2


def _bucket(days: int) -> int:
    return max(DAYS_BUCKET, int(math.ceil(days / DAYS_BUCKET)) * DAYS_BUCKET)


def _payload(series: PriceSeries) -> dict:
    return {"ticker": series.ticker, "closes": series.closes,
            "dates": series.dates, "synthetic": series.synthetic}


def _series(payload: dict) -> PriceSeries:
    return PriceSeries(ticker=payload["ticker"], closes=payload["closes"],
                       dates=payload["dates"], synthetic=payload["synthetic"])


def _trim(series: PriceSeries, days: int) -> PriceSeries:
    if len(series) <= days:
        return series
    return PriceSeries(ticker=series.ticker, closes=series.closes[-days:],
                       dates=series.dates[-days:], synthetic=series.synthetic)


def _cache_get(key: str):
    try:
        return cache.get(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shared bar cache read failed (%s); bypassing cache", exc)
        return None


def _cache_set(key: str, value, ttl: int) -> None:
    try:
        cache.set(key, value, ttl)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shared bar cache write failed (%s)", exc)


def _cache_add(key: str, ttl: int) -> bool:
    try:
        return cache.add(key, "1", ttl)
    except Exception as exc:  # noqa: BLE001
        # On a cache outage behave as the fetcher: never block the pipeline
        # (waiting on a lock nobody can see would just burn the wait budget).
        logger.warning("Shared bar cache lock failed (%s); fetching directly", exc)
        return True


def _cache_delete(key: str) -> None:
    try:
        cache.delete(key)
    except Exception:  # noqa: BLE001
        pass


class SharedCacheProvider(BaseProvider):
    """Serve bars from the shared (Redis) cache; on a miss, fetch upstream at
    most once per (ticker, bucket) fleet-wide and publish the result. News
    passes straight through to the primary."""

    def __init__(self, primary: BaseProvider, ttl_seconds=None,
                 synthetic_ttl_seconds=None, wait_seconds=None):
        self.primary = primary
        # ``name`` records the configured primary; per-call truth about the data
        # source lives on ``PriceSeries.synthetic`` (same rule as ResilientProvider).
        self.name = primary.name
        self.ttl = int(ttl_seconds if ttl_seconds is not None
                       else getattr(settings, "MARKETDATA_SHARED_CACHE_TTL", 300))
        self.synthetic_ttl = int(
            synthetic_ttl_seconds if synthetic_ttl_seconds is not None
            else getattr(settings, "MARKETDATA_SHARED_CACHE_SYNTHETIC_TTL", 30))
        self.wait = float(wait_seconds if wait_seconds is not None
                          else getattr(settings, "MARKETDATA_FETCH_WAIT", 10.0))

    def _key(self, ticker: str, bucket: int) -> str:
        return f"quantai:bars:{ticker.upper().strip()}:{bucket}"

    def _lock_key(self, ticker: str, bucket: int) -> str:
        return self._key(ticker, bucket) + ":fetch"

    def history(self, ticker: str, days: int = 180) -> PriceSeries:
        # Clamp: days <= 0 would make _trim's [-days:] slice return the FULL
        # series (negative zero slicing), the opposite of what was asked.
        days = max(1, int(days))
        bucket = _bucket(days)
        key = self._key(ticker, bucket)

        payload = _cache_get(key)
        if payload is not None:
            return _trim(_series(payload), days)

        if _cache_add(self._lock_key(ticker, bucket), FETCH_LOCK_TTL):
            try:
                # Double-check under the lock: a concurrent fetcher may have
                # published and released between our miss and our acquire.
                payload = _cache_get(key)
                if payload is not None:
                    return _trim(_series(payload), days)
                return _trim(self._fetch_and_store(ticker, bucket, key), days)
            finally:
                _cache_delete(self._lock_key(ticker, bucket))

        # Another worker is fetching this bucket right now — wait for its result.
        deadline = time.monotonic() + self.wait
        while time.monotonic() < deadline:
            time.sleep(_WAIT_STEP_SECONDS)
            payload = _cache_get(key)
            if payload is not None:
                return _trim(_series(payload), days)

        # The fetcher stalled or died. Fetch directly rather than fail — a
        # duplicate upstream call beats returning nothing.
        logger.warning("Single-flight wait for %s (%sd bucket) timed out; fetching directly",
                       ticker, bucket)
        return _trim(self._fetch_and_store(ticker, bucket, key), days)

    def _fetch_and_store(self, ticker: str, bucket: int, key: str) -> PriceSeries:
        series = self.primary.history(ticker, days=bucket)
        ttl = self.synthetic_ttl if series.synthetic else self.ttl
        if len(series) and ttl > 0:
            _cache_set(key, _payload(series), ttl)
        return series

    def news(self, ticker: str, limit: int = 5):
        return self.primary.news(ticker, limit)
