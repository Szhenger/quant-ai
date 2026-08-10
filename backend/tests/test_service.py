"""Fleet-wide shared bar cache + single-flight coalescing (marketdata.service).

Uses the test LocMem cache (cleared between tests by conftest's autouse
fixture) and a counting fake provider — the semantics under Redis are the same.
"""
import datetime as dt

from django.core.cache import cache

from marketdata.providers import BaseProvider, PriceSeries
from marketdata.service import SharedCacheProvider, _bucket


class _CountingProvider(BaseProvider):
    name = "counting"

    def __init__(self, synthetic: bool = False):
        self.calls = 0
        self.synthetic = synthetic

    def history(self, ticker, days=180):
        self.calls += 1
        base = dt.date(2025, 1, 1)
        return PriceSeries(
            ticker=ticker.upper(),
            closes=[float(i + 1) for i in range(days)],
            dates=[(base + dt.timedelta(days=i)).isoformat() for i in range(days)],
            synthetic=self.synthetic,
        )

    def news(self, ticker, limit=5):
        return [{"title": "n", "source": "counting"}]


def _service(provider, **kw):
    kw.setdefault("ttl_seconds", 300)
    kw.setdefault("synthetic_ttl_seconds", 300)
    kw.setdefault("wait_seconds", 0.0)  # tests never sit in the wait loop
    return SharedCacheProvider(provider, **kw)


def test_second_call_served_from_shared_cache():
    p = _CountingProvider()
    svc = _service(p)
    a = svc.history("AAPL", days=120)
    b = svc.history("AAPL", days=120)
    assert p.calls == 1
    assert len(a) == 120 and len(b) == 120
    assert b.closes == a.closes
    assert b.synthetic is False


def test_different_lookbacks_share_one_bucket_fetch():
    p = _CountingProvider()
    svc = _service(p)
    assert len(svc.history("AAPL", days=60)) == 60
    assert len(svc.history("AAPL", days=170)) == 170
    assert p.calls == 1  # both served by the single 180-bar bucket fetch


def test_cache_is_per_ticker():
    p = _CountingProvider()
    svc = _service(p)
    svc.history("AAPL", days=60)
    svc.history("MSFT", days=60)
    assert p.calls == 2


def test_bucket_rounds_up_to_window():
    assert _bucket(1) == 180
    assert _bucket(180) == 180
    assert _bucket(181) == 360
    assert _bucket(485) == 540


def test_synthetic_flag_survives_the_cache():
    # Honesty: a cached fallback series must still say it is synthetic.
    p = _CountingProvider(synthetic=True)
    svc = _service(p)
    first = svc.history("AAPL", days=60)
    second = svc.history("AAPL", days=60)
    assert p.calls == 1
    assert first.synthetic is True
    assert second.synthetic is True


def test_synthetic_zero_ttl_is_not_cached():
    # With synthetic caching disabled, every call retries the primary.
    p = _CountingProvider(synthetic=True)
    svc = _service(p, synthetic_ttl_seconds=0)
    svc.history("AAPL", days=60)
    svc.history("AAPL", days=60)
    assert p.calls == 2


def test_fetch_lock_is_released():
    p = _CountingProvider()
    svc = _service(p)
    svc.history("AAPL", days=60)
    assert cache.get(svc._lock_key("AAPL", 180)) is None


def test_lock_holder_rechecks_cache_before_fetching(monkeypatch):
    # Miss -> acquire lock -> another fetcher's just-published bars must be
    # found by the re-check, not re-fetched upstream.
    p = _CountingProvider()
    svc = _service(p)
    payload = {"ticker": "AAPL", "closes": [1.0, 2.0],
               "dates": ["2025-01-01", "2025-01-02"], "synthetic": False}
    gets = iter([None, payload])
    monkeypatch.setattr("marketdata.service._cache_get", lambda key: next(gets))
    series = svc.history("AAPL", days=2)
    assert p.calls == 0
    assert series.closes == [1.0, 2.0]


def test_waiter_falls_back_to_direct_fetch_when_fetcher_stalls():
    p = _CountingProvider()
    svc = _service(p)  # wait_seconds=0: gives up waiting immediately
    cache.add(svc._lock_key("AAPL", 180), "1", 60)  # simulate a stalled fetcher
    series = svc.history("AAPL", days=60)
    assert p.calls == 1
    assert len(series) == 60


def test_news_passes_through_uncached():
    p = _CountingProvider()
    svc = _service(p)
    assert svc.news("AAPL") == [{"title": "n", "source": "counting"}]
