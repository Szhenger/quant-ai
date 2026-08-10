"""Market-data providers.

A small, pluggable interface with two implementations:

* ``YFinanceProvider`` — real Yahoo Finance data (no API key required).
* ``SyntheticProvider`` — deterministic seeded random walk, used offline and in
  tests so the whole pipeline runs anywhere.

``get_provider()`` picks based on ``settings.MARKETDATA_PROVIDER`` and always
wraps the primary in a ``ResilientProvider`` so a transient data-source failure
degrades to synthetic data instead of crashing strategy evaluation.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import random
from dataclasses import dataclass, field
from typing import List

from django.conf import settings

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Raised when a provider cannot return usable data."""


@dataclass
class PriceSeries:
    ticker: str
    closes: List[float] = field(default_factory=list)
    dates: List[str] = field(default_factory=list)
    # True when these prices are synthetic (a deterministic random walk), NOT real
    # market data. The flag travels with the data so no caller can mistake a
    # degraded fallback for a real quote.
    synthetic: bool = False

    def __len__(self) -> int:
        return len(self.closes)

    @property
    def latest(self) -> float | None:
        return self.closes[-1] if self.closes else None


class BaseProvider:
    name = "base"

    def history(self, ticker: str, days: int = 180) -> PriceSeries:  # pragma: no cover
        raise NotImplementedError

    def news(self, ticker: str, limit: int = 5) -> List[dict]:  # pragma: no cover
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Synthetic (deterministic, offline)
# --------------------------------------------------------------------------- #
class SyntheticProvider(BaseProvider):
    name = "synthetic"

    def _seed(self, ticker: str) -> int:
        digest = hashlib.sha256(ticker.upper().encode()).hexdigest()
        return int(digest, 16) % (2 ** 32)

    def history(self, ticker: str, days: int = 180) -> PriceSeries:
        days = max(2, int(days))
        rng = random.Random(self._seed(ticker))
        price = 20.0 + (self._seed(ticker) % 480)  # starting price 20..500
        drift = rng.uniform(-0.0004, 0.0006)
        vol = rng.uniform(0.008, 0.03)
        closes: List[float] = []
        for _ in range(days):
            shock = rng.gauss(drift, vol)
            price = max(0.5, price * (1 + shock))
            closes.append(round(price, 2))
        today = dt.date.today()
        dates = [(today - dt.timedelta(days=days - 1 - i)).isoformat() for i in range(days)]
        return PriceSeries(ticker=ticker.upper(), closes=closes, dates=dates, synthetic=True)

    def news(self, ticker: str, limit: int = 5) -> List[dict]:
        t = ticker.upper()
        headlines = [
            f"{t}: Analysts weigh in after latest price action",
            f"Sector rotation puts {t} back in focus for macro desks",
            f"{t} options volume spikes amid volatility",
            f"What the recent move in {t} means for positioning",
            f"{t} technicals flash a signal traders are watching",
        ]
        return [{"title": h, "source": "synthetic", "published_at": None} for h in headlines[:limit]]


# --------------------------------------------------------------------------- #
# yfinance (real data)
# --------------------------------------------------------------------------- #
class YFinanceProvider(BaseProvider):
    name = "yfinance"

    def history(self, ticker: str, days: int = 180) -> PriceSeries:
        import yfinance as yf

        # Pull extra calendar days to cover weekends/holidays, then trim.
        period_days = int(days * 1.6) + 10
        df = yf.Ticker(ticker).history(period=f"{period_days}d", auto_adjust=True, timeout=20)
        if df is None or df.empty or "Close" not in df:
            raise ProviderError(f"No price data returned for {ticker!r}")
        closes = [float(x) for x in df["Close"].tolist()][-days:]
        dates = [d.date().isoformat() for d in df.index][-days:]
        if len(closes) < 2:
            raise ProviderError(f"Insufficient price history for {ticker!r}")
        return PriceSeries(ticker=ticker.upper(), closes=closes, dates=dates)

    def news(self, ticker: str, limit: int = 5) -> List[dict]:
        import yfinance as yf

        try:
            raw = yf.Ticker(ticker).news or []
        except Exception:  # noqa: BLE001
            raw = []
        out = []
        for item in raw[:limit]:
            content = item.get("content", item)
            out.append({
                "title": content.get("title") or item.get("title", ""),
                "source": (content.get("provider") or {}).get("displayName", "yfinance"),
                "published_at": content.get("pubDate") or item.get("providerPublishTime"),
            })
        return out


# --------------------------------------------------------------------------- #
# Resilience wrapper
# --------------------------------------------------------------------------- #
class ResilientProvider(BaseProvider):
    """Try the primary provider; on any failure fall back to synthetic data.

    Honesty contract: a degraded fallback is never disguised as real data.
    ``history`` returns the fallback's ``PriceSeries`` verbatim, so its
    ``synthetic=True`` flag reaches the caller; ``news`` only substitutes
    synthetic (``source="synthetic"``) headlines when the primary actually
    *fails* — an empty-but-successful real result is returned as-is rather than
    fabricated over.
    """

    def __init__(self, primary: BaseProvider, fallback: BaseProvider):
        self.primary = primary
        self.fallback = fallback
        # ``name`` records which primary is configured. It is NOT a claim about a
        # given call's data source — that truth lives on ``PriceSeries.synthetic``
        # and on each news item's ``source``.
        self.name = primary.name

    def history(self, ticker: str, days: int = 180) -> PriceSeries:
        try:
            return self.primary.history(ticker, days)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Provider %s failed for %s (%s); using synthetic fallback",
                           self.primary.name, ticker, exc)
            return self.fallback.history(ticker, days)

    def news(self, ticker: str, limit: int = 5) -> List[dict]:
        try:
            # Return the real result even when empty — do NOT fabricate headlines
            # over a successful "no news" response.
            return self.primary.news(ticker, limit)
        except Exception:  # noqa: BLE001
            return self.fallback.news(ticker, limit)


def _maybe_cache(provider: BaseProvider) -> BaseProvider:
    """Wrap a provider in the local Parquet/DuckDB bar cache when it is both
    enabled (``MARKETDATA_CACHE``) and available (DuckDB importable)."""
    if not getattr(settings, "MARKETDATA_CACHE", False):
        return provider
    from .barstore import CachingProvider, bar_store_available

    if not bar_store_available():
        logger.info("MARKETDATA_CACHE is on but duckdb is not installed; skipping cache.")
        return provider
    return CachingProvider(provider)


def _maybe_shared_cache(provider: BaseProvider) -> BaseProvider:
    """Outermost layer: fleet-wide Redis bar cache with single-flight fetch
    coalescing (``feeder.service``), unless ``MARKETDATA_SHARED_CACHE`` is off."""
    if not getattr(settings, "MARKETDATA_SHARED_CACHE", True):
        return provider
    from .service import SharedCacheProvider

    return SharedCacheProvider(provider)


def get_provider() -> BaseProvider:
    mode = getattr(settings, "MARKETDATA_PROVIDER", "auto")
    synthetic = SyntheticProvider()
    if mode == "synthetic":
        return synthetic
    if mode == "yfinance":
        return _maybe_shared_cache(_maybe_cache(ResilientProvider(YFinanceProvider(), synthetic)))
    # auto
    try:
        import yfinance  # noqa: F401
        return _maybe_shared_cache(_maybe_cache(ResilientProvider(YFinanceProvider(), synthetic)))
    except ImportError:
        logger.info("yfinance not installed; using synthetic market data.")
        return synthetic
