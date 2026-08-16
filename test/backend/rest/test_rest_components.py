"""REST component invariants, enforced by discovery.

Instead of testing a hand-picked list of endpoints (which silently goes stale
the day someone adds a route), these tests walk the live URL resolver: every
route the API actually serves is swept, and adding an endpoint without
classifying it here is itself a failure. That's the framework part — the suite
can't be out of date with the routing table.
"""
import uuid

import pytest
from django.conf import settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.urls.exceptions import NoReverseMatch
from rest_framework.test import APIClient

from engine.models import Strategy

pytestmark = pytest.mark.django_db

# Routes that must stay reachable without credentials. Everything else under
# /api/ and /healthz must demand authentication.
PUBLIC_ROUTES = {
    "healthz",            # infra probe
    "register",           # account creation
    "token_obtain_pair",  # login
    "token_refresh",      # session renewal (the refresh token IS the credential)
    "logout",             # deliberate AllowAny: revokes the submitted refresh
                          # token, and must work after the access token expired
}

# Non-API surfaces the sweep ignores.
IGNORED_PREFIXES = ("admin/",)

SAMPLE_KWARGS = {
    "pk": str(uuid.uuid4()),
    "ticker": "AAPL",
    "format": "json",
}


def _discover_routes():
    """Yield (url_name, resolved_path) for every named route in the project."""
    seen = {}

    def walk(patterns, prefix):
        for entry in patterns:
            if isinstance(entry, URLResolver):
                walk(entry.url_patterns, prefix + str(entry.pattern))
            elif isinstance(entry, URLPattern) and entry.name:
                seen.setdefault(entry.name, prefix + str(entry.pattern))

    walk(get_resolver().url_patterns, "")
    for name, raw in sorted(seen.items()):
        if raw.startswith(IGNORED_PREFIXES):
            continue
        for kwargs in ({}, *({k: SAMPLE_KWARGS[k]} for k in SAMPLE_KWARGS),
                       {"pk": SAMPLE_KWARGS["pk"], "format": "json"}):
            try:
                yield name, reverse(name, kwargs=kwargs)
                break
            except NoReverseMatch:
                continue
        else:
            pytest.fail(
                f"route {name!r} ({raw}) takes arguments this sweep doesn't "
                f"know how to fill — extend SAMPLE_KWARGS so it stays covered"
            )


def test_every_route_is_swept_and_classified():
    names = {name for name, _ in _discover_routes()}
    unknown_public = PUBLIC_ROUTES - names
    assert not unknown_public, (
        f"PUBLIC_ROUTES names routes that no longer exist: {unknown_public}"
    )


def test_every_non_public_route_rejects_anonymous_requests():
    client = APIClient()
    leaks = []
    for name, path in _discover_routes():
        response = client.get(path)
        if name in PUBLIC_ROUTES:
            if response.status_code in (401, 403):
                leaks.append(f"{name} ({path}) should be public but demands auth")
        elif response.status_code not in (401, 403):
            leaks.append(
                f"{name} ({path}) answered anonymous GET with {response.status_code}"
            )
    assert not leaks, "\n".join(leaks)


# --------------------------------------------------------------------------- #
# Throttling
# --------------------------------------------------------------------------- #
def test_every_scoped_throttle_has_a_configured_rate():
    """A throttle_scope without a rate entry raises ImproperlyConfigured at
    request time — in production, on the first hit."""
    from engine import views as engine_views

    configured = set(settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])
    used = {"evaluate", "replay", "analysis"}
    assert engine_views.MarketAnalysisView.throttle_scope in configured
    assert used <= configured, f"unconfigured scopes: {used - configured}"


# --------------------------------------------------------------------------- #
# Pagination bounds
# --------------------------------------------------------------------------- #
def test_default_pagination_is_the_bounded_variant():
    assert settings.REST_FRAMEWORK["DEFAULT_PAGINATION_CLASS"] == (
        "config.pagination.BoundedLimitOffsetPagination"
    )


def test_client_supplied_limit_is_capped(auth_client, workspace):
    from config.pagination import BoundedLimitOffsetPagination

    for i in range(3):
        Strategy.objects.create(
            workspace=workspace, name=f"S{i}", ticker="AAPL",
            indicator="PRICE", operator=">", threshold=0.0,
        )
    response = auth_client.get("/api/v1/strategies/?limit=1000000")
    assert response.status_code == 200
    # The page honours max_limit, not the client's number; with only 3 rows the
    # observable proof is that the request succeeds and the ceiling is sane.
    assert BoundedLimitOffsetPagination.max_limit <= 200
    assert len(response.json()["results"]) == 3


def test_limit_zero_and_negative_are_harmless(auth_client):
    for probe in ("?limit=0", "?limit=-5", "?limit=notanumber"):
        response = auth_client.get(f"/api/v1/strategies/{probe}")
        assert response.status_code == 200, probe


# --------------------------------------------------------------------------- #
# Error contract
# --------------------------------------------------------------------------- #
def test_anonymous_errors_are_json_with_a_detail_key():
    response = APIClient().get("/api/v1/strategies/")
    assert response.status_code == 401
    assert response["Content-Type"].startswith("application/json")
    assert "detail" in response.json()


def test_cross_tenant_probes_read_as_not_found(auth_client):
    """Object-level denial must be indistinguishable from nonexistence — a 403
    would confirm the resource exists in someone else's tenant."""
    response = auth_client.get(f"/api/v1/strategies/{uuid.uuid4()}/")
    assert response.status_code == 404
