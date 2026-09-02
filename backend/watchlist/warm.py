"""Stock-page warm markers: "a compile for this measure is in flight".

One marker per (watched ticker, measure) in the shared cache. The page view
sets it when it enqueues a compile (debounce) and reports ``refreshing`` while
it exists; the compile task clears it on completion. The TTL bounds a crashed
compile: the marker self-expires and the page stops reporting a refresh that
will never land.
"""
from django.core.cache import cache

STOCKPAGE_MEASURES = ("quantitative", "qualitative")
STOCKPAGE_WARM_TTL = 90


def stockpage_warm_key(watched_id, measure: str) -> str:
    return f"quantai:stockpage-warm:{watched_id}:{measure}"


def stockpage_refreshing(watched_id) -> bool:
    """True while any measure of this ticker's page is being (re)compiled."""
    keys = [stockpage_warm_key(watched_id, m) for m in STOCKPAGE_MEASURES]
    return any(v is not None for v in cache.get_many(keys).values())
