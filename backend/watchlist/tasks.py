"""Stock-page compilation on the worker fleet.

Each watched ticker compiles two measures on independent cadences:
  * qualitative (this week's news + Claude summary) every n hours;
  * quantitative (macroscale indicators) every m hours, retaining a compressed
    snapshot of the previous measure for continuity.

``refresh_stock_pages`` (Beat) fans out the due work; the two compile tasks do
the compute and persist. The API never runs a compile in-request: a page that
isn't ready is warmed with ``.delay`` (see ``watchlist.views``). On completion
each compile task clears its per-measure warm marker (how the page endpoint
reports ``refreshing``) and publishes ``stockpage.updated`` to the workspace
socket (how the console knows to refetch without polling).
"""
import gzip
import json
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from common.events import STOCKPAGE_UPDATED, publish
from .models import WatchedTicker, StockPage, QuantSnapshot
from .stockpage import build_quantitative, build_qualitative
from .warm import stockpage_warm_key

logger = logging.getLogger(__name__)


def _compress_measure(payload: dict) -> bytes:
    return gzip.compress(json.dumps(payload, separators=(",", ":")).encode())


def decompress_measure(blob) -> dict:
    """Inflate a QuantSnapshot.compressed blob back into its dict (used by the
    history endpoint)."""
    return json.loads(gzip.decompress(bytes(blob)).decode())


def _prune_snapshots(watched_ticker) -> None:
    keep = int(settings.STOCKPAGE_SNAPSHOT_RETENTION)
    stale = list(
        QuantSnapshot.objects.filter(watched_ticker=watched_ticker)
        .order_by("-taken_at")
        .values_list("id", flat=True)[keep:]
    )
    if stale:
        QuantSnapshot.objects.filter(id__in=stale).delete()


@shared_task(ignore_result=True)
def compile_stock_quantitative(watched_ticker_id: str, snapshot_previous: bool = True):
    """Recompute the macroscale quantitative measure and persist it, retaining a
    compressed snapshot of the previous measure first (continuity)."""
    try:
        wt = WatchedTicker.objects.get(id=watched_ticker_id)
    except WatchedTicker.DoesNotExist:
        return {"status": "not_found"}

    built = build_quantitative(wt.ticker)  # network/compute OUTSIDE the transaction
    now = timezone.now()
    StockPage.objects.get_or_create(watched_ticker=wt)
    with transaction.atomic():
        page = StockPage.objects.select_for_update().get(watched_ticker=wt)
        if snapshot_previous and page.quantitative_summary:
            QuantSnapshot.objects.create(
                watched_ticker=wt,
                compressed=_compress_measure({
                    "recomputed_at": page.recomputed_at.isoformat() if page.recomputed_at else None,
                    "summary": page.quantitative_summary,
                }),
            )
            _prune_snapshots(wt)
        page.quantitative = built["detailed"]
        page.quantitative_summary = built["summary"]
        page.data_synthetic = built["synthetic"] or bool((page.qualitative or {}).get("synthetic"))
        page.recomputed_at = now
        page.save(update_fields=[
            "quantitative", "quantitative_summary", "data_synthetic",
            "recomputed_at", "updated_at",
        ])
    # After the commit: the page endpoint stops reporting ``refreshing`` for
    # this measure only once the fresh numbers are actually readable.
    cache.delete(stockpage_warm_key(wt.id, "quantitative"))
    publish(wt.workspace_id, STOCKPAGE_UPDATED,
            watch_id=str(wt.id), ticker=wt.ticker, measure="quantitative")
    return {"status": "recomputed", "ticker": wt.ticker}


@shared_task(ignore_result=True)
def compile_stock_qualitative(watched_ticker_id: str):
    """Refresh the qualitative measure (this week's news + Claude summary)."""
    try:
        wt = WatchedTicker.objects.get(id=watched_ticker_id)
    except WatchedTicker.DoesNotExist:
        return {"status": "not_found"}

    built = build_qualitative(wt.ticker, user_id=wt.workspace.owner_id)
    now = timezone.now()
    StockPage.objects.get_or_create(watched_ticker=wt)
    with transaction.atomic():
        page = StockPage.objects.select_for_update().get(watched_ticker=wt)
        page.qualitative = built["detailed"]
        page.qualitative_summary = built["summary"]
        page.data_synthetic = built["synthetic"] or bool((page.quantitative or {}).get("synthetic"))
        page.refreshed_at = now
        page.save(update_fields=[
            "qualitative", "qualitative_summary", "data_synthetic",
            "refreshed_at", "updated_at",
        ])
    cache.delete(stockpage_warm_key(wt.id, "qualitative"))
    publish(wt.workspace_id, STOCKPAGE_UPDATED,
            watch_id=str(wt.id), ticker=wt.ticker, measure="qualitative")
    return {"status": "refreshed", "ticker": wt.ticker}


@shared_task(ignore_result=True)
def refresh_stock_pages():
    """Beat sweep: enqueue the due measures for every watched ticker.

    Cheap and idempotent — a ticker whose page is still fresh enqueues nothing.
    The per-ticker ``refresh_interval_hours`` (n) and ``recompute_interval_hours``
    (m) decide what is due; the sweep's own cadence only bounds latency."""
    now = timezone.now()
    qualitative = quantitative = 0
    qs = WatchedTicker.objects.select_related("page").iterator(chunk_size=500)
    for wt in qs:
        try:
            page = wt.page
        except StockPage.DoesNotExist:
            page = None
        due_qual = (
            page is None or page.refreshed_at is None
            or (now - page.refreshed_at) >= timedelta(hours=wt.refresh_interval_hours)
        )
        due_quant = (
            page is None or page.recomputed_at is None
            or (now - page.recomputed_at) >= timedelta(hours=wt.recompute_interval_hours)
        )
        if due_qual:
            compile_stock_qualitative.delay(str(wt.id))
            qualitative += 1
        if due_quant:
            compile_stock_quantitative.delay(str(wt.id))
            quantitative += 1
    return {"qualitative": qualitative, "quantitative": quantitative}
