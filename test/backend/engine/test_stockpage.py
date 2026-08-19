"""Watchlist stock-page MVP: the two measures, the n/m cadences, and the
compressed continuity snapshots. Runs on the synthetic provider (offline) with
Claude disabled, so the qualitative summary uses its graceful fallback."""
from datetime import datetime, timedelta, timezone as tz
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone

from feeder.stockpage import build_quantitative, build_qualitative, _within_week
from identity.models import WatchedTicker, StockPage, QuantSnapshot
from engine.tasks import (
    compile_stock_quantitative,
    compile_stock_qualitative,
    refresh_stock_pages,
    decompress_measure,
)

pytestmark = pytest.mark.django_db


def _watch(workspace, ticker="AAPL", **kw):
    return WatchedTicker.objects.create(workspace=workspace, ticker=ticker, **kw)


# --- The two measures (pure builders) ---------------------------------------

def test_build_quantitative_has_detailed_and_summary():
    out = build_quantitative("AAPL")
    assert out["synthetic"] is True  # tests use the synthetic provider
    detailed = out["detailed"]
    assert detailed["ticker"] == "AAPL"
    assert "indicators" in detailed and detailed["indicators"]  # full catalog
    assert detailed["week"]["closes"]  # the week slice for display
    summary = out["summary"]
    assert "headline" in summary and summary["measures"]
    # The summary surfaces plain-language readings a non-expert can act on.
    keys = {m["key"] for m in summary["measures"]}
    assert {"RSI", "VOLATILITY"} & keys
    assert all("reading" in m for m in summary["measures"])


def test_build_qualitative_lists_news_and_summarizes_this_week():
    out = build_qualitative("AAPL")
    detailed = out["detailed"]
    assert detailed["window_days"] == 7
    assert detailed["news"]  # synthetic headlines
    assert detailed["summary"]  # a summary string
    # No ANTHROPIC_API_KEY in tests -> the graceful fallback, not a crash.
    assert detailed["summary_source"] == "fallback"
    assert out["summary"]["article_count"] == len(detailed["news"])


def test_within_week_filters_old_headlines_but_keeps_undated():
    now = datetime(2026, 8, 19, tzinfo=tz.utc)
    items = [
        {"title": "recent", "published_at": "2026-08-18T00:00:00Z"},
        {"title": "old", "published_at": "2026-01-01T00:00:00Z"},
        {"title": "undated", "published_at": None},
    ]
    kept = {i["title"] for i in _within_week(items, now=now)}
    assert kept == {"recent", "undated"}  # old dropped, undated kept


# --- Persistence + API ------------------------------------------------------

def test_adding_a_ticker_warms_the_page_and_it_is_viewable(auth_client, workspace):
    resp = auth_client.post("/api/v1/watchlist/", {"ticker": "MSFT"}, format="json")
    assert resp.status_code == 201, resp.content
    wid = resp.data["id"]
    # Eager Celery compiled the page during the POST.
    page = auth_client.get(f"/api/v1/watchlist/{wid}/page/")
    assert page.status_code == 200, page.content
    body = page.data
    assert body["ticker"] == "MSFT"
    assert body["quantitative"]["indicators"]          # detailed quant
    assert body["quantitative_summary"]["measures"]    # summarised quant
    assert body["qualitative"]["news"]                 # detailed qual
    assert body["qualitative_summary"]["article_count"] >= 0  # summarised qual
    assert body["data_synthetic"] is True
    assert body["refreshed_at"] and body["recomputed_at"]


def test_page_action_never_compiles_inline_and_debounces(auth_client, workspace):
    # A ticker created directly (no warm-up) is not ready: the read path must NOT
    # compile inline (no provider fetch / paid Claude call in the request) — it
    # enqueues the compile and answers 202.
    wt = _watch(workspace, ticker="ZZZZ")
    with patch("engine.tasks.compile_stock_quantitative.delay") as q, \
         patch("engine.tasks.compile_stock_qualitative.delay") as ql:
        r1 = auth_client.get(f"/api/v1/watchlist/{wt.id}/page/")
        assert r1.status_code == 202
        assert r1.data["status"] == "computing"
        assert q.call_count == 1 and ql.call_count == 1
        # A second poll while the compile is in flight must NOT re-enqueue
        # (debounced) — otherwise focus-refetch/retry would re-spend Claude tokens.
        r2 = auth_client.get(f"/api/v1/watchlist/{wt.id}/page/")
        assert r2.status_code == 202
        assert q.call_count == 1 and ql.call_count == 1


def test_refresh_is_async_and_returns_202(auth_client, workspace):
    wid = auth_client.post("/api/v1/watchlist/", {"ticker": "AAPL"}, format="json").data["id"]
    with patch("engine.tasks.compile_stock_quantitative.delay") as q, \
         patch("engine.tasks.compile_stock_qualitative.delay") as ql:
        r = auth_client.post(f"/api/v1/watchlist/{wid}/refresh/")
        assert r.status_code == 202
        assert r.data["status"] == "refreshing"
        # force=True: an explicit refresh recomputes both, bypassing the debounce.
        assert q.called and ql.called


def test_client_sets_refresh_and_recompute_intervals(auth_client, workspace):
    wid = auth_client.post("/api/v1/watchlist/", {"ticker": "TSLA"}, format="json").data["id"]
    resp = auth_client.patch(f"/api/v1/watchlist/{wid}/",
                             {"refresh_interval_hours": 3, "recompute_interval_hours": 48},
                             format="json")
    assert resp.status_code == 200, resp.content
    wt = WatchedTicker.objects.get(id=wid)
    assert wt.refresh_interval_hours == 3
    assert wt.recompute_interval_hours == 48


def test_interval_bounds_are_enforced(auth_client, workspace):
    wid = auth_client.post("/api/v1/watchlist/", {"ticker": "NVDA"}, format="json").data["id"]
    bad = auth_client.patch(f"/api/v1/watchlist/{wid}/",
                            {"refresh_interval_hours": 0}, format="json")
    assert bad.status_code == 400


# --- Continuity: recompute snapshots the previous measure -------------------

def test_recompute_retains_a_compressed_snapshot(workspace):
    wt = _watch(workspace)
    compile_stock_quantitative(str(wt.id))          # first compute: no prior to snapshot
    assert QuantSnapshot.objects.filter(watched_ticker=wt).count() == 0
    compile_stock_quantitative(str(wt.id))          # second: snapshots the first
    snaps = QuantSnapshot.objects.filter(watched_ticker=wt)
    assert snaps.count() == 1
    # The snapshot round-trips and carries the prior quantitative summary.
    restored = decompress_measure(snaps.first().compressed)
    assert "summary" in restored and restored["summary"]["measures"]


def test_history_endpoint_returns_the_continuity_trail(auth_client, workspace):
    wid = auth_client.post("/api/v1/watchlist/", {"ticker": "AMD"}, format="json").data["id"]
    auth_client.post(f"/api/v1/watchlist/{wid}/refresh/")  # a second recompute -> one snapshot
    hist = auth_client.get(f"/api/v1/watchlist/{wid}/history/")
    assert hist.status_code == 200
    assert hist.data["ticker"] == "AMD"
    assert len(hist.data["snapshots"]) >= 1
    assert hist.data["snapshots"][0]["summary"]["measures"]


@override_settings(STOCKPAGE_SNAPSHOT_RETENTION=2)
def test_snapshot_retention_is_bounded(workspace):
    wt = _watch(workspace)
    for _ in range(5):
        compile_stock_quantitative(str(wt.id))
    assert QuantSnapshot.objects.filter(watched_ticker=wt).count() == 2


# --- The n/m sweep ----------------------------------------------------------

def test_sweep_enqueues_due_pages_and_skips_fresh(workspace):
    # A ticker whose page is brand new (never compiled) is due for both measures.
    fresh_ticker = _watch(workspace, ticker="GOOG")
    result = refresh_stock_pages()
    assert result["qualitative"] >= 1 and result["quantitative"] >= 1

    # After compiling and marking both measures fresh, it is no longer due.
    compile_stock_quantitative(str(fresh_ticker.id))
    compile_stock_qualitative(str(fresh_ticker.id))
    page = StockPage.objects.get(watched_ticker=fresh_ticker)
    assert page.refreshed_at and page.recomputed_at
    assert refresh_stock_pages() == {"qualitative": 0, "quantitative": 0}


def test_sweep_marks_due_when_interval_elapsed(workspace):
    wt = _watch(workspace, ticker="IBM", refresh_interval_hours=1, recompute_interval_hours=1)
    compile_stock_quantitative(str(wt.id))
    compile_stock_qualitative(str(wt.id))
    # Backdate the freshness stamps beyond both intervals.
    StockPage.objects.filter(watched_ticker=wt).update(
        refreshed_at=timezone.now() - timedelta(hours=2),
        recomputed_at=timezone.now() - timedelta(hours=2),
    )
    assert refresh_stock_pages() == {"qualitative": 1, "quantitative": 1}
