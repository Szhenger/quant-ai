"""Executable UX spec: full user journeys the product must never regress.

Where ``test/system`` pins individual endpoint contracts, these tests pin the
*experience* — whole sessions in the order a real user performs them, with the
invariants asserted mid-flow (badge arithmetic, exactly-once alerting, data
honesty, tenancy walls, session revocation). A future PR that keeps every unit
test green but breaks the sequence — a cooldown that stops carrying across
evaluations, a badge that drifts, an edit that clobbers a sibling field — fails
here.

House rules for editing this file:
* Tests read top-to-bottom as user sessions. Keep them that way.
* Every assertion states a user-visible promise, not an implementation detail.
* If a PR intentionally changes one of these promises, that PR must change the
  assertion in the same commit — that's the review conversation working.
"""
from unittest.mock import patch

import pytest

from engine.models import Strategy
from engine.tasks import sweep_due_strategies

from .uxspec import assert_field_error, assert_honest_alert, signup

pytestmark = pytest.mark.django_db


def test_first_session_journey():
    """Register → follow markets → build a strategy → get alerted in-app →
    triage the alert → replay the signal → log out. The whole first session."""
    # A too-weak password is refused with a field error the login page renders.
    from .uxspec import ConsoleClient
    probe = ConsoleClient()
    assert_field_error(probe.register("sam", "sam@example.com", "a"), "password")

    sam = signup("sam")

    # The account is immediately usable: one default workspace, empty state.
    assert sam.get("/strategies/").data["count"] == 0

    # Follow two markets; a duplicate follow is a clean field error, not a 500.
    assert sam.post("/watchlist/", {"ticker": "AAPL", "note": "core"}).status_code == 201
    assert sam.post("/watchlist/", {"ticker": "NVDA", "note": ""}).status_code == 201
    assert_field_error(sam.post("/watchlist/", {"ticker": "aapl", "note": "dupe"}), "ticker")

    # Market analysis works offline (synthetic) and says so; revalidation is
    # a free 304 so chart flipping stays instant.
    resp = sam.get("/markets/AAPL/analysis/?days=120")
    body = resp.json()
    assert body["synthetic"] is True and len(body["closes"]) == 120
    revalidated = sam.get("/markets/AAPL/analysis/?days=120",
                          HTTP_IF_NONE_MATCH=resp.headers["ETag"])
    assert revalidated.status_code == 304 and not revalidated.content

    # Build a strategy with custom indicator params from the simple form.
    resp = sam.post("/strategies/", {
        "name": "AAPL always-on", "ticker": "AAPL", "indicator": "PRICE",
        "operator": ">", "threshold": 0, "ai_enabled": False,
        "params": {},
    })
    assert resp.status_code == 201, resp.content
    strategy = resp.json()

    # Manual evaluate fires; the alert appears in the list with the full
    # audit trail, honestly labeled, and bumps the unread badge to exactly 1.
    assert sam.post(f"/strategies/{strategy['id']}/evaluate/").json()["status"] == "alerted"
    alerts = sam.get("/alerts/").json()["results"]
    assert len(alerts) == 1
    assert_honest_alert(alerts[0])
    assert alerts[0]["condition_detail"]["result"] is True
    assert alerts[0]["delivery"]["in_app"]["ok"] is True
    assert sam.get("/alerts/unread-count/").json() == {"unread": 1}

    # Exactly-once: an immediate re-evaluate lands in cooldown, no second alert.
    assert sam.post(f"/strategies/{strategy['id']}/evaluate/").json()["status"] == "cooldown"
    assert len(sam.get("/alerts/").json()["results"]) == 1

    # Triage: mark read; badge returns to 0 (never negative).
    assert sam.post(f"/alerts/{alerts[0]['id']}/mark-read/").json()["is_read"] is True
    assert sam.get("/alerts/unread-count/").json() == {"unread": 0}

    # Replay answers "when would this have fired?" over exactly the window
    # asked for, on warmed-up indicators, and admits synthetic data.
    rep = sam.get(f"/strategies/{strategy['id']}/replay/?days=30&cooldown_bars=5").json()
    assert rep["bars"] == 30 and rep["synthetic"] is True and rep["fire_count"] >= 1

    # Logout is a real revocation: the refresh token dies server-side.
    refresh = sam.refresh
    assert sam.logout().status_code == 205
    from rest_framework.test import APIClient
    reused = APIClient().post("/api/v1/auth/token/refresh/", {"refresh": refresh},
                              format="json")
    assert reused.status_code == 401


def test_strategy_lifecycle_journey():
    """Create → edit → pause → resume → rotate secret → delete: a strategy is
    managed through its whole life without ever being rebuilt from scratch."""
    rita = signup("rita")
    strategy = rita.post("/strategies/", {
        "name": "Fast z-score", "ticker": "AAPL", "indicator": "Z_SCORE",
        "params": {"window": 10}, "operator": "<", "threshold": 3,
        "ai_enabled": False,
    }).json()
    assert strategy["params"] == {"window": 10}  # custom params survive create

    # Edit changes exactly what was asked — siblings are untouched.
    edited = rita.patch(f"/strategies/{strategy['id']}/", {
        "threshold": -1.5, "cooldown_minutes": 30,
    }).json()
    assert edited["threshold"] == -1.5 and edited["cooldown_minutes"] == 30
    assert edited["ticker"] == "AAPL" and edited["params"] == {"window": 10}
    assert edited["webhook_secret"] == strategy["webhook_secret"]

    # Pause stops the scheduler from touching it (it was due: never evaluated).
    assert rita.patch(f"/strategies/{strategy['id']}/", {"status": "paused"}) \
        .json()["status"] == "paused"
    with patch("engine.tasks.evaluate_strategy.delay") as delay:
        assert sweep_due_strategies()["queued"] == 0
    assert delay.call_count == 0

    # Resume puts it back on the schedule.
    assert rita.patch(f"/strategies/{strategy['id']}/", {"status": "active"}) \
        .json()["status"] == "active"
    with patch("engine.tasks.evaluate_strategy.delay") as delay:
        assert sweep_due_strategies()["queued"] == 1

    # Rotating the webhook secret changes the secret and nothing else.
    rotated = rita.post(f"/strategies/{strategy['id']}/rotate-secret/").json()
    assert rotated["webhook_secret"] != strategy["webhook_secret"]
    assert len(rotated["webhook_secret"]) == 32
    assert rotated["threshold"] == -1.5 and rotated["name"] == "Fast z-score"

    # Deleting the strategy never deletes its history: fired alerts survive,
    # detached (strategy null) but fully readable.
    firing = rita.post("/strategies/", {
        "name": "burst", "ticker": "NVDA", "indicator": "PRICE",
        "operator": ">", "threshold": 0, "ai_enabled": False,
    }).json()
    assert rita.post(f"/strategies/{firing['id']}/evaluate/").json()["status"] == "alerted"
    assert rita.delete(f"/strategies/{firing['id']}/").status_code == 204
    survivors = rita.get("/alerts/").json()["results"]
    assert len(survivors) == 1
    assert survivors[0]["strategy"] is None and survivors[0]["strategy_name"] is None
    assert_honest_alert(survivors[0])


def test_hostile_client_journey():
    """Everything a hostile (or buggy) client throws must bounce off cleanly:
    field-keyed 400s for bad input, hard tenancy walls, dead tokens stay dead."""
    mallory = signup("mallory")

    # Input guardrails — each names its field so the UI can render it.
    assert_field_error(mallory.post("/strategies/", {
        "name": "x", "ticker": "AAPL", "indicator": "PRICE",
        "operator": ">", "threshold": "NaN"}), "threshold")
    assert_field_error(mallory.post("/strategies/", {
        "name": "x", "ticker": "AAPL", "indicator": "Z_SCORE",
        "params": {"window": 10 ** 9}, "operator": "<", "threshold": -2}), "params")
    assert_field_error(mallory.post("/strategies/", {
        "name": "x", "ticker": "AAPL", "indicator": "PRICE", "operator": ">",
        "threshold": 0, "webhook_url": "http://169.254.169.254/latest"}), "webhook_url")
    assert_field_error(mallory.post("/watchlist/", {"ticker": "not a ticker!!"}), "ticker")

    # Tenancy walls: a victim's resources are invisible AND inoperable.
    victim = signup("victim")
    secret_strategy = victim.post("/strategies/", {
        "name": "private", "ticker": "TSLA", "indicator": "PRICE",
        "operator": ">", "threshold": 0, "ai_enabled": False,
    }).json()

    mallory.select_workspace(victim.workspace_id)          # forged header
    assert mallory.get("/strategies/").status_code == 404
    mallory.select_workspace()                              # back to own workspace
    for probe in (
        mallory.get(f"/strategies/{secret_strategy['id']}/"),
        mallory.post(f"/strategies/{secret_strategy['id']}/rotate-secret/"),
        mallory.post(f"/strategies/{secret_strategy['id']}/evaluate/"),
        mallory.delete(f"/strategies/{secret_strategy['id']}/"),
    ):
        assert probe.status_code == 404, probe.content
    # ...and the victim's strategy is genuinely untouched.
    assert Strategy.objects.filter(id=secret_strategy["id"]).exists()

    # No workspace header at all is a 403 (the console re-selects on this).
    mallory.api.defaults.pop("HTTP_X_WORKSPACE_ID")
    assert mallory.get("/strategies/").status_code == 403
    mallory.select_workspace()

    # A logged-out session is over: neither refresh nor a replayed logout
    # brings it back, and logout stays idempotent (never an error to repeat).
    dead_refresh = mallory.refresh
    assert mallory.logout().status_code == 205
    assert mallory.post("/auth/logout/", {"refresh": dead_refresh}).status_code == 205
    from rest_framework.test import APIClient
    assert APIClient().post("/api/v1/auth/token/refresh/", {"refresh": dead_refresh},
                            format="json").status_code == 401
