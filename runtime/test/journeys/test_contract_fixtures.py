"""Golden-fixture contract pins — the backend half of the dual pin.

``fixtures/*.json`` is the single source of truth for the wire shapes the
console depends on. This module proves the LIVE API still produces exactly
those shapes (key-for-key, at every nesting level); the frontend's
``console/src/api/contracts.test.ts`` proves ``types.ts`` matches the very
same files at compile time.

The loop this creates: change a serializer → this fails → you update the
fixture → the frontend contract test fails to compile → you update types.ts
(and the key maps) in the same PR. The shape can never drift on one side only.
"""
import pytest

from .uxspec import assert_same_shape, load_fixture, signup

pytestmark = pytest.mark.django_db


@pytest.fixture()
def session():
    return signup("contractor")


def test_auth_tokens_match_fixture(session):
    resp = session.api.post("/api/v1/auth/token/", {
        "username": "contractor", "password": "contractor-sturdy-pass-9",
    }, format="json")
    assert_same_shape(resp.json(), load_fixture("auth_tokens"))


def test_strategy_matches_fixture(session):
    resp = session.post("/strategies/", {
        "name": "AAPL breathing", "ticker": "AAPL", "indicator": "PRICE",
        "operator": ">", "threshold": 0, "ai_enabled": False,
    })
    assert resp.status_code == 201, resp.content
    assert_same_shape(resp.json(), load_fixture("strategy"))


def test_alert_matches_fixture(session):
    strategy = session.post("/strategies/", {
        "name": "AAPL breathing", "ticker": "AAPL", "indicator": "PRICE",
        "operator": ">", "threshold": 0, "ai_enabled": False,
    }).json()
    assert session.post(f"/strategies/{strategy['id']}/evaluate/").json()["status"] == "alerted"
    alert = session.get("/alerts/").json()["results"][0]
    assert_same_shape(alert, load_fixture("alert"))


def test_market_analysis_matches_fixture(session):
    resp = session.get("/markets/AAPL/analysis/?days=120")
    assert_same_shape(resp.json(), load_fixture("market_analysis"))


def test_replay_matches_fixture(session):
    strategy = session.post("/strategies/", {
        "name": "AAPL breathing", "ticker": "AAPL", "indicator": "PRICE",
        "operator": ">", "threshold": 0, "ai_enabled": False,
    }).json()
    resp = session.get(f"/strategies/{strategy['id']}/replay/?days=30")
    assert_same_shape(resp.json(), load_fixture("replay"))
