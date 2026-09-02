"""Provider honesty: a degraded synthetic fallback is never disguised as real data."""
from markets import analyze_market
from markets.providers import (
    BaseProvider,
    PriceSeries,
    ProviderError,
    ResilientProvider,
    SyntheticProvider,
)


class _Boom(BaseProvider):
    name = "boom"

    def history(self, ticker, days=180):
        raise ProviderError("primary down")

    def news(self, ticker, limit=5):
        raise ProviderError("primary down")


class _Real(BaseProvider):
    name = "real"

    def __init__(self, news_items=None):
        self._news = news_items if news_items is not None else [{"title": "x", "source": "real"}]

    def history(self, ticker, days=180):
        return PriceSeries(ticker.upper(), [1.0, 2.0, 3.0], ["a", "b", "c"], synthetic=False)

    def news(self, ticker, limit=5):
        return self._news


def test_synthetic_series_is_flagged():
    assert SyntheticProvider().history("AAPL", days=30).synthetic is True


def test_real_series_is_not_flagged():
    assert _Real().history("AAPL").synthetic is False


def test_resilient_fallback_flags_data_as_synthetic():
    # Even though the configured primary is 'boom', the returned data is synthetic
    # and must say so — no spoofing the primary's name onto fabricated prices.
    series = ResilientProvider(_Boom(), SyntheticProvider()).history("AAPL", 30)
    assert series.synthetic is True


def test_resilient_success_is_not_flagged():
    series = ResilientProvider(_Real(), SyntheticProvider()).history("AAPL", 30)
    assert series.synthetic is False


def test_resilient_does_not_fabricate_news_over_empty_real_result():
    # A successful "no news" must not be papered over with synthetic headlines.
    p = ResilientProvider(_Real(news_items=[]), SyntheticProvider())
    assert p.news("AAPL") == []


def test_resilient_uses_synthetic_news_only_on_failure():
    items = ResilientProvider(_Boom(), SyntheticProvider()).news("AAPL")
    assert items and all(n["source"] == "synthetic" for n in items)


def test_analyze_market_reports_true_source(settings):
    # Test settings pin the synthetic provider, so the snapshot must own up to it.
    settings.MARKETDATA_PROVIDER = "synthetic"
    data = analyze_market("AAPL", days=60)
    assert data["synthetic"] is True
    assert data["provider"] == "synthetic"
