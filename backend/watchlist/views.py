from django.core.cache import cache
from django.db import IntegrityError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from identity.workspaces import resolve_active_workspace
from .models import WatchedTicker, StockPage
from .serializers import WatchedTickerSerializer, StockPageSerializer
from .tasks import compile_stock_qualitative, compile_stock_quantitative, decompress_measure
from .warm import STOCKPAGE_WARM_TTL, stockpage_refreshing, stockpage_warm_key


class WatchedTickerViewSet(viewsets.ModelViewSet):
    """The active workspace's watchlist (markets the user follows), plus each
    ticker's compiled stock page (qualitative + quantitative measures)."""

    serializer_class = WatchedTickerSerializer
    # Declared so the per-action ``throttle_scope="analysis"`` is a settable
    # attribute (DRF applies action kwargs only for attributes that exist).
    throttle_scope = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # schema introspection
            return WatchedTicker.objects.none()
        workspace = resolve_active_workspace(self.request)
        # select_related("page"): the serializer reads page freshness per row.
        return WatchedTicker.objects.filter(workspace=workspace).select_related("page")

    def perform_create(self, serializer):
        workspace = resolve_active_workspace(self.request)
        try:
            watched = serializer.save(workspace=workspace)
        except IntegrityError as exc:
            # Backstop for the serializer's exists() check losing a race.
            raise ValidationError(
                {"ticker": "This ticker is already on the watchlist."}
            ) from exc
        # Warm the stock page off the request path (see _warm_stock_page).
        self._warm_stock_page(watched, page=None)

    @staticmethod
    def _warm_stock_page(watched, *, page, force: bool = False) -> None:
        """Enqueue the compile tasks for whichever measures are missing — always
        via ``.delay`` (never inline), so no request thread ever blocks on a
        provider fetch or a paid Claude call.

        Debounced with an atomic per-measure cache marker so repeated polls /
        focus-refetches while a compile is in flight can't fan out duplicate
        compiles and re-spend Claude tokens. ``force`` (explicit user refresh)
        bypasses the debounce. The compile task clears its marker when it
        finishes, so the marker doubles as the "refresh in flight" signal the
        ``page`` action reports back to the client."""
        plan = (
            ("quantitative", compile_stock_quantitative,
             page is None or page.recomputed_at is None),
            ("qualitative", compile_stock_qualitative,
             page is None or page.refreshed_at is None),
        )
        for measure, task, missing in plan:
            if not (force or missing):
                continue
            key = stockpage_warm_key(watched.id, measure)
            if force:
                cache.set(key, "1", STOCKPAGE_WARM_TTL)
            elif not cache.add(key, "1", STOCKPAGE_WARM_TTL):
                continue  # this measure's compile is already in flight
            task.delay(str(watched.id))

    @extend_schema(responses=OpenApiTypes.OBJECT, operation_id="watchlist_page")
    @action(detail=True, methods=["get"],
            throttle_classes=[ScopedRateThrottle], throttle_scope="analysis")
    def page(self, request, pk=None):
        """The compiled stock page for this ticker (both measures, detailed +
        summarised). Never compiles inline: if a measure isn't ready yet it warms
        it in the background and answers 202 so the client can poll."""
        watched = self.get_object()
        try:
            page = watched.page
        except StockPage.DoesNotExist:
            page = None
        ready = page is not None and page.recomputed_at is not None and page.refreshed_at is not None
        if not ready:
            self._warm_stock_page(watched, page=page)
            return Response({"status": "computing", "ticker": watched.ticker}, status=202)
        # ``refreshing``: a forced refresh keeps serving the last compiled page
        # (the timestamps stay set) — this flag is how the client knows to keep
        # polling until the recompile lands instead of silently showing stale
        # numbers until its next focus refetch.
        return Response({
            **StockPageSerializer(page).data,
            "refreshing": stockpage_refreshing(watched.id),
        })

    @extend_schema(request=None, responses=OpenApiTypes.OBJECT, operation_id="watchlist_refresh")
    @action(detail=True, methods=["post"],
            throttle_classes=[ScopedRateThrottle], throttle_scope="analysis")
    def refresh(self, request, pk=None):
        """Force a recompute of both measures in the background (the next page
        fetch will pick up the fresh data). Returns 202 immediately — the compute
        (provider fetch + Claude summary + snapshot) runs on the worker fleet, not
        the web request."""
        watched = self.get_object()
        try:
            page = watched.page
        except StockPage.DoesNotExist:
            page = None
        self._warm_stock_page(watched, page=page, force=True)
        return Response({"status": "refreshing", "ticker": watched.ticker}, status=202)

    @extend_schema(responses=OpenApiTypes.OBJECT, operation_id="watchlist_history")
    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """Retained (compressed) prior quantitative measures — the macroscale
        continuity trail for this ticker."""
        watched = self.get_object()
        snapshots = []
        for snap in watched.snapshots.all():
            try:
                payload = decompress_measure(snap.compressed)
            except Exception:  # noqa: BLE001 — a corrupt snapshot must not 500 the trail
                payload = {"summary": None, "recomputed_at": None}
            snapshots.append({
                "taken_at": snap.taken_at,
                "recomputed_at": payload.get("recomputed_at"),
                "summary": payload.get("summary"),
            })
        return Response({"ticker": watched.ticker, "snapshots": snapshots})
