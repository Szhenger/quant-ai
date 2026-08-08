"""Local Parquet/DuckDB bar store + caching provider.

Skipped automatically where duckdb is not installed (the store degrades to a
no-op there, and get_provider never wraps in caching)."""
import datetime as dt

import pytest

pytest.importorskip("duckdb")

from marketdata.barstore import BarStore, CachingProvider  # noqa: E402
from marketdata.providers import BaseProvider, PriceSeries  # noqa: E402


class _CountingProvider(BaseProvider):
    name = "counting"

    def __init__(self, rows: int):
        self.rows = rows
        self.history_calls = 0
        self.news_calls = 0

    def history(self, ticker, days=180):
        self.history_calls += 1
        base = dt.date(2025, 1, 1)
        closes = [float(i + 1) for i in range(self.rows)]
        dates = [(base + dt.timedelta(days=i)).isoformat() for i in range(self.rows)]
        return PriceSeries(ticker.upper(), closes, dates, synthetic=False)

    def news(self, ticker, limit=5):
        self.news_calls += 1
        return [{"title": "real", "source": "real"}]


def test_write_then_read_roundtrip(tmp_path):
    store = BarStore(root=str(tmp_path))
    series = PriceSeries(
        "AAPL", [10.0, 11.0, 12.0], ["2026-01-01", "2026-01-02", "2026-01-03"], synthetic=False
    )
    store.write(series)
    got = store.read("AAPL", days=3)
    assert got is not None
    assert got.closes == [10.0, 11.0, 12.0]
    assert got.dates == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert got.synthetic is False


def test_synthetic_series_is_never_cached(tmp_path):
    store = BarStore(root=str(tmp_path))
    store.write(PriceSeries("AAPL", [1.0, 2.0], ["2026-01-01", "2026-01-02"], synthetic=True))
    assert store.read("AAPL", days=2) is None
    assert store.age_seconds("AAPL") is None


def test_caching_provider_serves_second_call_from_cache(tmp_path):
    primary = _CountingProvider(rows=180)
    cp = CachingProvider(primary, store=BarStore(root=str(tmp_path)), ttl_seconds=3600)
    a = cp.history("AAPL", days=180)
    b = cp.history("AAPL", days=180)
    assert primary.history_calls == 1          # second call served from cache
    assert b.closes == a.closes
    assert b.synthetic is False


def test_caching_provider_refetches_when_stale(tmp_path):
    primary = _CountingProvider(rows=180)
    cp = CachingProvider(primary, store=BarStore(root=str(tmp_path)), ttl_seconds=0)
    cp.history("AAPL", days=180)
    cp.history("AAPL", days=180)
    assert primary.history_calls == 2          # ttl=0 => always stale


def test_caching_provider_passes_news_through(tmp_path):
    primary = _CountingProvider(rows=180)
    cp = CachingProvider(primary, store=BarStore(root=str(tmp_path)))
    assert cp.news("AAPL") == [{"title": "real", "source": "real"}]
    assert primary.news_calls == 1
