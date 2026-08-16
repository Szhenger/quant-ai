"""Local historical bar store — Parquet files on disk, queried with DuckDB.

An OPTIONAL caching layer in front of a market-data provider so repeated strategy
evaluations reuse locally-stored bars instead of re-hitting the upstream source.

Design choices:
  * DuckDB-only. It reads and writes Parquet natively via SQL, so there is no
    PyArrow dependency and no long-lived connection to manage.
  * Degrades to a no-op when ``duckdb`` is not installed — the core pipeline never
    depends on it. ``get_provider`` only wraps in caching when both the
    ``MARKETDATA_CACHE`` setting is on and DuckDB is importable.
  * Synthetic data is NEVER written to the cache. The store holds real bars only,
    so a cache read can always be reported as ``synthetic=False`` honestly.
"""
from __future__ import annotations

import logging
import math
import os
import time
from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4

from django.conf import settings

from .providers import BaseProvider, PriceSeries

logger = logging.getLogger(__name__)


def bar_store_available() -> bool:
    try:
        import duckdb  # noqa: F401
        return True
    except ImportError:
        return False


class BarStore:
    """Per-ticker Parquet bar cache under a root directory."""

    def __init__(self, root: Optional[str] = None):
        self.root = Path(root or getattr(settings, "MARKETDATA_CACHE_DIR", ".marketdata_cache"))

    def _path(self, ticker: str) -> Path:
        return self.root / f"{ticker.upper()}.parquet"

    def age_seconds(self, ticker: str) -> Optional[float]:
        """Seconds since this ticker's cache was last written, or None if absent."""
        path = self._path(ticker)
        if not path.exists():
            return None
        return time.time() - path.stat().st_mtime

    def read(self, ticker: str, days: int) -> Optional[PriceSeries]:
        """The most recent ``days`` cached bars for ``ticker`` (oldest-first), or None."""
        if not bar_store_available():
            return None
        path = self._path(ticker)
        if not path.exists():
            return None
        import duckdb

        try:
            rows = duckdb.sql(
                "SELECT date, close FROM read_parquet($p) ORDER BY date DESC LIMIT $n",
                params={"p": path.as_posix(), "n": int(days)},
            ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Bar store read failed for %s: %s", ticker, exc)
            return None
        if len(rows) < 2:
            return None
        rows = list(reversed(rows))  # back to oldest-first
        return PriceSeries(
            ticker=ticker.upper(),
            closes=[float(r[1]) for r in rows],
            dates=[str(r[0]) for r in rows],
            synthetic=False,  # only real bars are ever cached
        )

    def _read_all(self, path: Path) -> Dict[str, float]:
        """Every cached (date -> close) row at ``path``, or {} if absent/unreadable."""
        if not path.exists():
            return {}
        import duckdb

        try:
            rows = duckdb.sql(
                "SELECT date, close FROM read_parquet($p)",
                params={"p": path.as_posix()},
            ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Bar store merge-read failed for %s: %s", path, exc)
            return {}
        return {str(r[0]): float(r[1]) for r in rows}

    def write(self, series: PriceSeries) -> None:
        """Persist a real price series as Parquet. Synthetic/empty series are ignored.

        Safe under concurrent writers: bars are written to a uniquely-named temp
        file and atomically renamed over the final path, so readers see the old
        or the new file, never a partial one.

        A refresh that overlaps the existing cache consistently is MERGED, so a
        short fetch never truncates longer history. If overlapping dates
        disagree (upstream re-adjusted history, e.g. after a split/dividend) or
        the ranges are disjoint (a gap), the new series REPLACES the cache —
        mixing adjustment bases or bridging a hole would corrupt indicators.
        """
        if not bar_store_available() or series.synthetic or len(series) == 0:
            return
        import duckdb

        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(series.ticker)

        # strict: a dates/closes length mismatch must fail loudly, not silently
        # truncate the series it caches.
        new = dict(zip(series.dates, (float(c) for c in series.closes), strict=True))
        existing = self._read_all(path)
        overlap = [d for d in new if d in existing]
        if overlap and all(math.isclose(existing[d], new[d], rel_tol=1e-4) for d in overlap):
            rows = sorted({**existing, **new}.items())  # ISO dates: lexicographic == chronological
        else:
            rows = sorted(new.items())

        tmp = path.with_name(f".{path.name}.{os.getpid()}-{uuid4().hex[:8]}.tmp")
        try:
            con = duckdb.connect()
            try:
                con.execute("CREATE TABLE bars(date VARCHAR, close DOUBLE)")
                con.executemany("INSERT INTO bars VALUES (?, ?)", [[d, c] for d, c in rows])
                con.execute("COPY bars TO ? (FORMAT PARQUET)", [tmp.as_posix()])
            finally:
                con.close()
            os.replace(tmp, path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Bar store write failed for %s: %s", series.ticker, exc)
            tmp.unlink(missing_ok=True)


class CachingProvider(BaseProvider):
    """Serve bars from a local Parquet cache when fresh; otherwise fetch upstream
    and refresh the cache. News always passes straight through to the primary."""

    def __init__(self, primary: BaseProvider, store: Optional[BarStore] = None,
                 ttl_seconds: Optional[int] = None):
        self.primary = primary
        self.name = primary.name
        self.store = store or BarStore()
        self.ttl = int(ttl_seconds if ttl_seconds is not None
                       else getattr(settings, "MARKETDATA_CACHE_TTL", 3600))

    def history(self, ticker: str, days: int = 180) -> PriceSeries:
        age = self.store.age_seconds(ticker)
        if age is not None and age < self.ttl:
            cached = self.store.read(ticker, days)
            if cached is not None and len(cached) >= days:
                return cached
        series = self.primary.history(ticker, days)
        self.store.write(series)  # no-ops on synthetic/empty
        return series

    def news(self, ticker: str, limit: int = 5):
        return self.primary.news(ticker, limit)
