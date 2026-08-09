"""Web-tier performance & concurrency behavior.

Covers the interactive read path (single-flight compute cache, ETag
revalidation, gzip), the alerts read/write path (cursor pagination, unread
count, bulk mark-read, join hygiene), and the WebSocket heartbeat.
"""
import threading
import time

import pytest
from asgiref.sync import async_to_sync
from django.core.cache import cache

import strategies.views as views_mod
from core.caching import cached_compute, stable_key
from core.models import Workspace
from strategies.consumers import AlertConsumer
from strategies.models import Strategy, Alert


# --------------------------------------------------------------------------
# cached_compute: single-flight semantics
# --------------------------------------------------------------------------

def test_cached_compute_computes_once_per_key():
    calls = []
    def compute():
        calls.append(1)
        return {"answer": 42}

    key = stable_key("t", {"a": 1})
    v1, hit1 = cached_compute(key, 60, compute)
    v2, hit2 = cached_compute(key, 60, compute)
    assert v1 == v2 == {"answer": 42}
    assert (hit1, hit2) == (False, True)
    assert len(calls) == 1


def test_cached_compute_distinct_keys_do_not_collide():
    key_a = stable_key("t", {"ticker": "AAPL", "days": 90})
    key_b = stable_key("t", {"ticker": "AAPL", "days": 91})
    assert key_a != key_b
    cached_compute(key_a, 60, lambda: "a")
    value, _ = cached_compute(key_b, 60, lambda: "b")
    assert value == "b"


def test_cached_compute_caches_falsy_values():
    calls = []
    def compute():
        calls.append(1)
        return {}

    key = stable_key("t", {"empty": True})
    cached_compute(key, 60, compute)
    value, from_cache = cached_compute(key, 60, compute)
    assert value == {} and from_cache is True
    assert len(calls) == 1


def test_cached_compute_waiter_picks_up_published_value():
    """While another request holds the flight lock, a waiter polls and adopts
    the published value instead of recomputing."""
    key = stable_key("t", {"flight": 1})
    cache.add(f"{key}:flight", "1", 30)  # someone else is computing

    def publish_soon():
        time.sleep(0.15)
        cache.set(key, {"v": "theirs"}, 60)

    t = threading.Thread(target=publish_soon)
    t.start()
    try:
        value, from_cache = cached_compute(key, 60, lambda: "mine", wait_budget=2.0)
    finally:
        t.join()
    assert value == "theirs" and from_cache is True


def test_cached_compute_falls_back_when_flight_holder_dies():
    """If the computing worker never publishes, a waiter computes itself
    (bounded waiting — never a deadlock, never an error)."""
    key = stable_key("t", {"flight": 2})
    cache.add(f"{key}:flight", "1", 30)  # holder that will never publish
    value, from_cache = cached_compute(key, 60, lambda: "fallback", wait_budget=0)
    assert value == "fallback" and from_cache is False


# --------------------------------------------------------------------------
# Analysis endpoint: server cache + conditional GET + gzip
# --------------------------------------------------------------------------

def test_analysis_computed_once_across_requests(auth_client, monkeypatch):
    real = views_mod.analyze_market
    calls = []
    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)
    monkeypatch.setattr(views_mod, "analyze_market", counting)

    r1 = auth_client.get("/api/v1/markets/AAPL/analysis/")
    r2 = auth_client.get("/api/v1/markets/AAPL/analysis/")
    assert r1.status_code == r2.status_code == 200
    assert len(calls) == 1  # second request served from the compute cache

    auth_client.get("/api/v1/markets/AAPL/analysis/", {"days": 90})
    assert len(calls) == 2  # different window -> different key


def test_analysis_etag_roundtrip_returns_304(auth_client):
    first = auth_client.get("/api/v1/markets/AAPL/analysis/")
    assert first.status_code == 200
    etag = first["ETag"]
    assert etag

    again = auth_client.get("/api/v1/markets/AAPL/analysis/", HTTP_IF_NONE_MATCH=etag)
    assert again.status_code == 304
    assert not again.content  # revalidation carries no body

    # A weak-etag echo (e.g. transformed by GZip middleware) still matches.
    weak = auth_client.get("/api/v1/markets/AAPL/analysis/", HTTP_IF_NONE_MATCH=f"W/{etag}")
    assert weak.status_code == 304


def test_analysis_gzip_on_the_wire(auth_client):
    resp = auth_client.get("/api/v1/markets/AAPL/analysis/", HTTP_ACCEPT_ENCODING="gzip")
    assert resp.status_code == 200
    assert resp.get("Content-Encoding") == "gzip"


# --------------------------------------------------------------------------
# Replay endpoint: content-addressed cache + conditional GET
# --------------------------------------------------------------------------

def _make_strategy(workspace, **overrides):
    defaults = dict(
        workspace=workspace,
        name="Z dip",
        ticker="AAPL",
        indicator="Z_SCORE",
        params={"window": 20},
        operator="<",
        threshold=-1.0,
        ai_enabled=False,
    )
    defaults.update(overrides)
    return Strategy.objects.create(**defaults)


def test_replay_cache_shared_across_identical_conditions(auth_client, workspace, monkeypatch):
    real = views_mod.replay_condition
    calls = []
    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)
    monkeypatch.setattr(views_mod, "replay_condition", counting)

    s1 = _make_strategy(workspace, name="one")
    s2 = _make_strategy(workspace, name="two")

    r1 = auth_client.get(f"/api/v1/strategies/{s1.id}/replay/", {"days": 90})
    r2 = auth_client.get(f"/api/v1/strategies/{s2.id}/replay/", {"days": 90})
    assert r1.status_code == r2.status_code == 200
    # Identical condition tree + ticker + window -> one computation.
    assert len(calls) == 1
    # But the payload still carries each strategy's own identity.
    assert r1.data["strategy_id"] == str(s1.id)
    assert r2.data["strategy_id"] == str(s2.id)
    assert r1.data["fires"] == r2.data["fires"]


def test_replay_etag_roundtrip_returns_304(auth_client, workspace):
    s = _make_strategy(workspace)
    first = auth_client.get(f"/api/v1/strategies/{s.id}/replay/", {"days": 90})
    assert first.status_code == 200
    again = auth_client.get(
        f"/api/v1/strategies/{s.id}/replay/", {"days": 90},
        HTTP_IF_NONE_MATCH=first["ETag"],
    )
    assert again.status_code == 304


# --------------------------------------------------------------------------
# Alerts: cursor pagination, unread count, bulk mark-read, query hygiene
# --------------------------------------------------------------------------

def _bulk_alerts(workspace, n, strategy=None, is_read=False):
    Alert.objects.bulk_create([
        Alert(
            workspace=workspace,
            strategy=strategy,
            ticker="AAPL",
            indicator="Z_SCORE",
            operator="<",
            threshold=-2.0,
            metric_value=-2.5,
            message=f"alert {i}",
            is_read=is_read,
        )
        for i in range(n)
    ])


def test_alert_cursor_pagination_walks_all_pages(auth_client, workspace):
    _bulk_alerts(workspace, 120)

    seen = set()
    url = "/api/v1/alerts/"
    pages = 0
    while url:
        resp = auth_client.get(url)
        assert resp.status_code == 200
        assert "count" not in resp.data  # cursor pages don't COUNT the table
        for row in resp.data["results"]:
            assert row["id"] not in seen, "cursor pages must not overlap"
            seen.add(row["id"])
        pages += 1
        url = resp.data["next"]
        assert pages < 10, "pagination did not terminate"

    assert len(seen) == 120
    assert pages == 3  # 50 + 50 + 20


def test_unread_count_scoped_to_workspace(auth_client, workspace, user):
    other = Workspace.objects.create(name="Other", owner=user)
    _bulk_alerts(workspace, 5)
    _bulk_alerts(workspace, 3, is_read=True)
    _bulk_alerts(other, 4)

    resp = auth_client.get("/api/v1/alerts/unread-count/")
    assert resp.status_code == 200
    assert resp.data == {"unread": 5}


def test_mark_all_read_single_statement(auth_client, workspace, user):
    other = Workspace.objects.create(name="Other", owner=user)
    _bulk_alerts(workspace, 5)
    _bulk_alerts(other, 4)

    resp = auth_client.post("/api/v1/alerts/mark-all-read/")
    assert resp.status_code == 200
    assert resp.data == {"updated": 5}
    assert auth_client.get("/api/v1/alerts/unread-count/").data == {"unread": 0}
    # The other workspace's alerts are untouched.
    assert Alert.objects.filter(workspace=other, is_read=False).count() == 4
    # Idempotent: nothing left to update.
    assert auth_client.post("/api/v1/alerts/mark-all-read/").data == {"updated": 0}


def test_alert_list_query_count_is_flat(auth_client, workspace, django_assert_max_num_queries):
    """strategy.name is rendered per row; select_related keeps the page at a
    constant query count instead of one join query per alert."""
    strategy = _make_strategy(workspace)
    _bulk_alerts(workspace, 20, strategy=strategy)

    with django_assert_max_num_queries(6):
        resp = auth_client.get("/api/v1/alerts/")
        assert len(resp.data["results"]) == 20
        assert resp.data["results"][0]["strategy_name"] == strategy.name


# --------------------------------------------------------------------------
# WebSocket heartbeat
# --------------------------------------------------------------------------

def test_consumer_answers_ping_with_pong():
    consumer = AlertConsumer()
    sent = []

    async def capture(payload):
        sent.append(payload)

    consumer.send_json = capture
    async_to_sync(consumer.receive_json)({"type": "ping", "t": 1723200000})
    assert sent == [{"type": "pong", "t": 1723200000}]


def test_consumer_ignores_non_ping_frames():
    consumer = AlertConsumer()
    sent = []

    async def capture(payload):
        sent.append(payload)

    consumer.send_json = capture
    async_to_sync(consumer.receive_json)({"type": "subscribe"})
    async_to_sync(consumer.receive_json)("not-a-dict")
    assert sent == []
