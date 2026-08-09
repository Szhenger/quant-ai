from django.conf import settings
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.caching import cached_compute, conditional_response, stable_key
from core.workspaces import resolve_active_workspace
from marketdata import (
    INDICATOR_SPECS,
    OPERATORS,
    analyze_market,
    get_provider,
    condition_lookback_days,
    describe_tree,
    replay_condition,
)
from .models import Strategy, Alert
from .serializers import StrategySerializer, AlertSerializer
from .compiler import compile_graph, GraphCompilationError


def _int_param(request, name, default):
    raw = request.query_params.get(name)
    if raw is None:
        raw = request.data.get(name) if hasattr(request.data, "get") else None
    try:
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


class StrategyViewSet(viewsets.ModelViewSet):
    """CRUD for user-defined market-monitoring strategies, scoped to the active workspace."""

    serializer_class = StrategySerializer

    def get_queryset(self):
        workspace = resolve_active_workspace(self.request)
        return Strategy.objects.filter(workspace=workspace)

    def get_throttles(self):
        # Replay and manual evaluation do real work (provider fetch + indicator
        # sweep, and evaluate may call the LLM); rate-limit them under the
        # "compute" scope on top of the global user throttle.
        if getattr(self, "action", None) in ("replay", "evaluate"):
            self.throttle_scope = "compute"
        return super().get_throttles()

    def perform_create(self, serializer):
        workspace = resolve_active_workspace(self.request)
        serializer.save(workspace=workspace)

    @action(detail=False, methods=["post"], url_path="deploy-graph")
    def deploy_graph(self, request):
        """Compile a React Flow graph into a strategy and persist it."""
        workspace = resolve_active_workspace(request)
        payload = request.data
        try:
            compiled = compile_graph(
                payload.get("nodes", []),
                payload.get("edges", payload.get("connections", [])),
            )
        except GraphCompilationError as exc:
            raise ValidationError({"graph": str(exc)})

        data = {
            "name": payload.get("name") or f"{compiled['ticker']} {compiled['indicator']}",
            "ticker": compiled["ticker"],
            "condition": compiled["condition"],
            "ai_enabled": compiled["ai_enabled"],
            "ai_prompt": compiled["ai_prompt"],
        }
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save(workspace=workspace)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def evaluate(self, request, pk=None):
        """Manually evaluate a strategy now (useful for testing)."""
        strategy = self.get_object()
        from .tasks import evaluate_strategy  # local import avoids app-loading cycles
        result = evaluate_strategy(str(strategy.id))
        return Response(result)

    @action(detail=True, methods=["get", "post"])
    def replay(self, request, pk=None):
        """Signal replay: walk this strategy's condition over historical bars and
        report every bar where it *would* have fired. Deterministic and offline
        (no AI, no alert side effects) — a would-fire timeline, not a P&L backtest.

        Query/body params: ``days`` (30-1000, default 365), ``cooldown_bars``
        (0-365, default 0) to dedupe a persistent condition.
        """
        strategy = self.get_object()
        tree = strategy.condition_tree()
        days = max(30, min(_int_param(request, "days", 365), 1000))
        cooldown_bars = max(0, min(_int_param(request, "cooldown_bars", 0), 365))

        def compute():
            provider = get_provider()
            # Fetch enough history for the indicators to warm up *and* cover the window.
            series = provider.history(
                strategy.ticker, days=max(days, condition_lookback_days(tree))
            )
            result = replay_condition(
                tree, series.closes, series.dates, cooldown_bars=cooldown_bars
            )
            return {
                "provider": "synthetic" if series.synthetic else provider.name,
                "synthetic": series.synthetic,
                "bars": result["bars"],
                "fire_count": result["fire_count"],
                "fires": result["fires"],
                "dates": series.dates,
                "closes": series.closes,
            }

        # Content-addressed: keyed by what the replay is a function of — the
        # condition tree, ticker and window — NOT the strategy id, so identical
        # conditions (across strategies or users) share one cache entry. Market
        # data is not tenant data; the tenant boundary is enforced above by
        # get_object() against the workspace-scoped queryset.
        key = stable_key("replay", {
            "tree": tree,
            "ticker": strategy.ticker,
            "days": days,
            "cooldown_bars": cooldown_bars,
            "provider": settings.MARKETDATA_PROVIDER,
        })
        replayed, _ = cached_compute(key, settings.REPLAY_CACHE_TTL, compute)

        payload = {
            "strategy_id": str(strategy.id),
            "ticker": strategy.ticker,
            "condition": describe_tree(tree),
            "cooldown_bars": cooldown_bars,
            **replayed,
        }
        return conditional_response(request, payload)


class AlertCursorPagination(CursorPagination):
    """Keyset pagination for the one table that grows without bound.

    Offset pagination scans and discards ``offset`` rows on every page — page
    100 of an alert history costs 100x page 1. A cursor page is a range scan
    from the last-seen key, so every page costs the same, and rows arriving
    concurrently (alerts fire in the background constantly) can't shift the
    window and duplicate/skip entries the way a moving offset does.
    """

    page_size = 50
    max_page_size = 200
    page_size_query_param = "page_size"
    ordering = ("-created_at", "-id")  # id breaks created_at ties deterministically


class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AlertSerializer
    pagination_class = AlertCursorPagination

    def get_queryset(self):
        workspace = resolve_active_workspace(self.request)
        # select_related: the serializer renders strategy.name — without the
        # join the list view issues one extra query per alert row.
        qs = Alert.objects.filter(workspace=workspace).select_related("strategy")
        unread = self.request.query_params.get("unread")
        if unread in ("1", "true", "True"):
            qs = qs.filter(is_read=False)
        return qs

    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        alert = self.get_object()
        alert.is_read = True
        alert.save(update_fields=["is_read"])
        return Response(self.get_serializer(alert).data)

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        """Cheap badge endpoint: an indexed COUNT, no serialization."""
        workspace = resolve_active_workspace(request)
        count = Alert.objects.filter(workspace=workspace, is_read=False).count()
        return Response({"unread": count})

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        """One UPDATE for the whole workspace — no read-modify-write race, and
        alerts that arrive after the statement snapshots stay unread."""
        workspace = resolve_active_workspace(request)
        updated = Alert.objects.filter(workspace=workspace, is_read=False).update(is_read=True)
        return Response({"updated": updated})


class MarketAnalysisView(APIView):
    """Quantitative snapshot for a ticker: price series + all indicators."""

    throttle_scope = "compute"

    def get(self, request, ticker):
        # Ensure the request is workspace-scoped (auth + tenant boundary).
        resolve_active_workspace(request)
        try:
            days = int(request.query_params.get("days", 180))
        except ValueError:
            days = 180
        days = max(30, min(days, 730))
        symbol = ticker.upper()

        # Market analysis is a pure function of public market data — the cache
        # is deliberately shared across users and workspaces.
        key = stable_key("analysis", {
            "ticker": symbol,
            "days": days,
            "provider": settings.MARKETDATA_PROVIDER,
        })
        payload, _ = cached_compute(
            key, settings.ANALYSIS_CACHE_TTL,
            lambda: analyze_market(symbol, days=days),
        )
        return conditional_response(request, payload)


class IndicatorCatalogView(APIView):
    """Metadata driving the strategy-builder UI: available indicators + operators."""

    def get(self, request):
        return Response({
            "indicators": [
                {"key": k, "label": v["label"], "unit": v["unit"],
                 "defaults": v["defaults"], "help": v["help"]}
                for k, v in INDICATOR_SPECS.items()
            ],
            "operators": [{"key": k, "label": v} for k, v in OPERATORS.items()],
        })
