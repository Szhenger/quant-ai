"""Single-flight compute caching and conditional-GET helpers for the web tier.

The interactive read path (market analysis, signal replay) is a pure function
of its inputs plus the provider's bars: same ticker, same window, same
condition tree -> same payload. That makes it safe to cache fleet-wide in
Redis. The part that needs care is the *stampede*: when a hot key is cold
(first hit, or just expired), every concurrent request would recompute at
once — N provider fetches and N indicator sweeps for one answer.

``cached_compute`` closes that with a flight lock: the first caller to a cold
key claims it (atomic ``cache.add``) and publishes the result; within one
process, Django's ASGI handler already serializes sync views onto a single
thread, so an in-process stampede cannot happen at all.

The deliberate non-feature: when the flight is held by ANOTHER process, we
compute anyway rather than sleep-wait for its result. Under an ASGI server,
every sync view in a process shares one thread — a request that sleeps
polling for a remote flight blocks every other request in its process, which
is a far worse failure than one duplicate computation (the payloads are
deterministic; last write wins). Callers that own their thread (Celery
workers, scripts) can opt into waiting with ``wait_budget``.

On top of the server cache, ``conditional_response`` gives clients a cheap
revalidation path: payloads carry a strong ETag (a hash of the canonical
JSON), and a matching ``If-None-Match`` turns the response into an empty 304.
"""
import hashlib
import json
import time
import uuid

from django.core.cache import cache
from rest_framework.response import Response

# How long a computing request may hold the flight lock. Comfortably longer
# than one provider fetch + indicator sweep; if the holder dies, the lock
# expires and the computation self-heals.
FLIGHT_LOCK_TTL = 30

# Opt-in waiters poll the cache at this interval while another process computes.
WAIT_INTERVAL = 0.05


def _canonical(payload) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode()


def stable_key(prefix: str, params) -> str:
    """Deterministic cache key from a JSON-serialisable parameter bundle."""
    digest = hashlib.sha256(_canonical(params)).hexdigest()
    return f"quantai:compute:{prefix}:{digest}"


def _resolve_ttl(ttl, value) -> int:
    """``ttl`` may be an int or a callable(value) -> int, so callers can cache
    degraded results (e.g. synthetic fallback data) for less time than good ones."""
    return ttl(value) if callable(ttl) else ttl


def cached_compute(key: str, ttl, compute, *, wait_budget: float = 0.0):
    """Return ``compute()``'s value through the shared cache.

    Returns ``(value, from_cache)``. Values are stored wrapped so a legitimate
    falsy payload is never confused with a cache miss.

    ``wait_budget`` — seconds to poll for another process's in-flight result
    before computing anyway. The default is 0 (never sleep): in the web tier,
    sleeping would block the process's single sync-view thread (see module
    docstring). Only set it from callers that own their thread.
    """
    hit = cache.get(key)
    if hit is not None:
        return hit["v"], True

    flight_key = f"{key}:flight"
    # cache.add is atomic (Redis SET NX). The token makes the release owned:
    # if our compute outlives FLIGHT_LOCK_TTL and someone else has since
    # claimed the flight, we must not delete *their* lock. Best-effort only —
    # the get/delete below is not a single atomic compare-and-delete, so a
    # claimant that slips in between them can still lose its lock; the cost is
    # one extra duplicate computation, which this module tolerates by design.
    token = uuid.uuid4().hex
    if cache.add(flight_key, token, FLIGHT_LOCK_TTL):
        try:
            value = compute()
            cache.set(key, {"v": value}, _resolve_ttl(ttl, value))
            return value, False
        finally:
            if cache.get(flight_key) == token:
                cache.delete(flight_key)

    # Another process is computing this exact payload.
    if wait_budget > 0:
        deadline = time.monotonic() + wait_budget
        while time.monotonic() < deadline:
            time.sleep(WAIT_INTERVAL)
            hit = cache.get(key)
            if hit is not None:
                return hit["v"], True

    # Compute ourselves: a duplicate computation is bounded and harmless
    # (deterministic payload, last write wins); blocking or failing is not.
    value = compute()
    cache.set(key, {"v": value}, _resolve_ttl(ttl, value))
    return value, False


def _normalize_etag(raw: str) -> str:
    return raw.strip().removeprefix("W/").strip('"')


def payload_etag(payload) -> str:
    """Strong ETag for a JSON payload (quote-wrapped, ready for the header)."""
    return f'"{hashlib.sha256(_canonical(payload)).hexdigest()[:40]}"'


def conditional_response(request, payload, *, max_age: int = 0) -> Response:
    """A DRF Response that honours ``If-None-Match`` with an empty 304.

    ``Cache-Control: private, no-cache`` by default: clients must revalidate,
    but revalidation is a hash comparison, not a recompute (the server-side
    compute cache answers) and not a re-download (the 304 has no body).
    """
    etag = payload_etag(payload)
    cache_control = f"private, max-age={max_age}" if max_age else "private, no-cache"
    headers = {"ETag": etag, "Cache-Control": cache_control}

    if request.method in ("GET", "HEAD"):
        client_tags = request.headers.get("If-None-Match", "")
        wanted = _normalize_etag(etag)
        if any(_normalize_etag(t) == wanted for t in client_tags.split(",") if t.strip()):
            return Response(status=304, headers=headers)
    return Response(payload, headers=headers)
