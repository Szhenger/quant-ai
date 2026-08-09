"""Single-flight compute caching and conditional-GET helpers for the web tier.

The interactive read path (market analysis, signal replay) is a pure function
of its inputs plus the provider's bars: same ticker, same window, same
condition tree -> same payload. That makes it safe to cache fleet-wide in
Redis. The part that needs care is the *stampede*: when a hot key is cold
(first hit, or just expired), every concurrent request would recompute at
once — N provider fetches and N indicator sweeps for one answer.

``cached_compute`` closes that with a single-flight lock: exactly one caller
computes and publishes; concurrent callers briefly poll the cache and pick up
the published value. If the computing worker dies, its flight lock expires
and a waiter falls back to computing itself — bounded waiting, never a
deadlock, and the cache self-heals.

On top of the server cache, ``conditional_response`` gives clients a cheap
revalidation path: payloads carry a strong ETag (a hash of the canonical
JSON), and a matching ``If-None-Match`` turns the response into an empty 304.
"""
import hashlib
import json
import time

from django.core.cache import cache
from rest_framework.response import Response

# How long the computing request may hold the flight lock. Comfortably longer
# than one provider fetch + indicator sweep; if the holder dies, the lock
# expires and the computation self-heals.
FLIGHT_LOCK_TTL = 30

# Waiters poll the cache at this interval while another request computes.
WAIT_INTERVAL = 0.05

# Max seconds a waiter waits on someone else's flight before computing itself.
WAIT_BUDGET = 10.0


def _canonical(payload) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode()


def stable_key(prefix: str, params) -> str:
    """Deterministic cache key from a JSON-serialisable parameter bundle."""
    digest = hashlib.sha256(_canonical(params)).hexdigest()
    return f"quantai:compute:{prefix}:{digest}"


def cached_compute(key: str, ttl: int, compute, *, wait_budget: float = WAIT_BUDGET):
    """Return ``compute()``'s value through the shared cache, single-flight.

    Returns ``(value, from_cache)``. Values are stored wrapped so a legitimate
    falsy payload is never confused with a cache miss.
    """
    hit = cache.get(key)
    if hit is not None:
        return hit["v"], True

    flight_key = f"{key}:flight"
    # cache.add is atomic (Redis SET NX): exactly one request wins the flight.
    if cache.add(flight_key, "1", FLIGHT_LOCK_TTL):
        try:
            value = compute()
            cache.set(key, {"v": value}, ttl)
            return value, False
        finally:
            cache.delete(flight_key)

    # Someone else is computing this exact payload: wait for their answer.
    deadline = time.monotonic() + wait_budget
    while time.monotonic() < deadline:
        time.sleep(WAIT_INTERVAL)
        hit = cache.get(key)
        if hit is not None:
            return hit["v"], True

    # The flight holder is dead or too slow — compute rather than fail.
    value = compute()
    cache.set(key, {"v": value}, ttl)
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
