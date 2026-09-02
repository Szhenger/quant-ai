from django.conf import settings
from django.db import transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers as rf_serializers
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from common.caching import cached_compute, conditional_response, provenance_ttl, stable_key
from identity.limits import ensure_strategy_capacity
from identity.models import Workspace
from identity.workspaces import resolve_active_workspace
from markets import get_provider, condition_lookback_days, describe_tree, replay_condition
from .models import Strategy, Alert, _new_webhook_secret
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
    # Base attr so per-action initkwargs (evaluate/replay set their own scope)
    # pass ViewSet.as_view's sanitize check; None = no scoped throttle.
    throttle_scope = None

    def get_queryset(self):
        # Schema introspection builds views with a fake request (no auth, no
        # workspace header); without this guard resolve_active_workspace raises
        # and drf-spectacular falls back to untyped path params.
        if getattr(self, "swagger_fake_view", False):
            return Strategy.objects.none()
        workspace = resolve_active_workspace(self.request)
        return Strategy.objects.filter(workspace=workspace)

    def perform_create(self, serializer):
        self._create_within_cap(serializer, resolve_active_workspace(self.request))

    @staticmethod
    def _create_within_cap(serializer, workspace) -> None:
        """Persist a new strategy unless the workspace is at its cap.

        The count-then-insert runs under the workspace's row lock, so two
        concurrent creates at cap-1 serialise: the second sees the first's
        row and is rejected, instead of both slipping past the same count."""
        with transaction.atomic():
            Workspace.objects.select_for_update().get(pk=workspace.pk)
            ensure_strategy_capacity(workspace)
            serializer.save(workspace=workspace)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={201: StrategySerializer})
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
            raise ValidationError({"graph": str(exc)}) from exc

        data = {
            "name": payload.get("name") or f"{compiled['ticker']} {compiled['indicator']}",
            "ticker": compiled["ticker"],
            "condition": compiled["condition"],
            "ai_enabled": compiled["ai_enabled"],
            "ai_prompt": compiled["ai_prompt"],
        }
        # Optional delivery/scheduling settings pass straight through to the
        # serializer — same validation as the plain form builder.
        for field in ("notify_in_app", "notify_email", "webhook_url",
                      "poll_interval_minutes", "cooldown_minutes"):
            if field in payload:
                data[field] = payload[field]
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self._create_within_cap(serializer, workspace)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=StrategySerializer)
    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request, pk=None):
        """Regenerate this strategy's webhook HMAC secret.

        For when a secret leaks (or as routine hygiene): deliveries signed
        after this call verify only against the new secret, so the receiver
        must be updated in the same operation. Returns the full strategy so
        the client can show the new secret immediately.
        """
        strategy = self.get_object()
        strategy.webhook_secret = _new_webhook_secret()
        # auto_now only fires for fields named in update_fields — include it.
        strategy.save(update_fields=["webhook_secret", "updated_at"])
        return Response(self.get_serializer(strategy).data)

    @extend_schema(request=None,
                   responses={200: OpenApiTypes.OBJECT, 202: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"],
            throttle_classes=[ScopedRateThrottle], throttle_scope="evaluate")
    def evaluate(self, request, pk=None):
        """Manually evaluate a strategy now (useful for testing).

        The evaluation (price fetch + optional AI call, up to ~a minute of
        network I/O) is dispatched to the worker fleet, NOT run in-request:
        under ASGI every sync view in a process shares one thread, so running
        it here would stall every other request in the process for the
        duration. When Celery runs eagerly (tests, dev without a worker) the
        result is available immediately and returned directly; otherwise the
        caller gets 202 and observes the outcome via strategy state / alerts.
        """
        strategy = self.get_object()
        from .tasks import evaluate_strategy  # local import avoids app-loading cycles
        async_result = evaluate_strategy.delay(str(strategy.id))
        if async_result.ready() and async_result.successful():
            result = async_result.result
            if isinstance(result, dict) and result.get("status") == "error":
                # Raw exception text is an internal detail (paths, hosts,
                # library internals) — the owner reads the specifics from
                # strategy.last_error; logs keep the full traceback.
                result = {"status": "error"}
            return Response(result)
        return Response({"status": "queued", "task_id": async_result.id},
                        status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        parameters=[
            OpenApiParameter("days", int, description="Replay window, 30-1000 bars."),
            OpenApiParameter("cooldown_bars", int,
                             description="Suppress fires within N bars of the last, 0-365."),
        ],
        request=None,
        responses=OpenApiTypes.OBJECT,
    )
    @action(detail=True, methods=["get", "post"],
            throttle_classes=[ScopedRateThrottle], throttle_scope="replay")
    def replay(self, request, pk=None):
        """Signal replay: walk this strategy's condition over historical bars and
        report every bar where it *would* have fired. Deterministic and offline
        (no AI, no alert side effects) — a would-fire timeline, not a P&L backtest.

        Query/body params: ``days`` (30-1000, default 365), ``cooldown_bars``
        (0-365, default 0) to dedupe a persistent condition.

        The response covers exactly the requested window: indicator lookback is
        fetched *in addition to* ``days``, so every reported bar evaluates on
        warmed-up indicators and ``bars == days`` (barring short upstream data).
        Fires before the window are not reported but do consume the cooldown,
        exactly as the live system's cooldown would carry into the window.
        """
        strategy = self.get_object()
        tree = strategy.condition_tree()
        days = max(30, min(_int_param(request, "days", 365), 1000))
        cooldown_bars = max(0, min(_int_param(request, "cooldown_bars", 0), 365))

        def compute():
            provider = get_provider()
            series = provider.history(
                strategy.ticker, days=days + condition_lookback_days(tree)
            )
            result = replay_condition(
                tree, series.closes, series.dates, cooldown_bars=cooldown_bars
            )
            # Trim to the trailing `days` bars and re-base fire indices so that
            # fires[i].index always indexes into the returned dates/closes arrays.
            offset = max(0, len(series.closes) - days)
            fires = [{**f, "index": f["index"] - offset}
                     for f in result["fires"] if f["index"] >= offset]
            closes = series.closes[offset:]
            dates = series.dates[offset:]
            return {
                "provider": "synthetic" if series.synthetic else provider.name,
                "synthetic": series.synthetic,
                "bars": len(closes),
                "fire_count": len(fires),
                "fires": fires,
                "dates": dates,
                "closes": closes,
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
        replayed, _ = cached_compute(key, provenance_ttl(settings.REPLAY_CACHE_TTL), compute)

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
        if getattr(self, "swagger_fake_view", False):  # schema introspection
            return Alert.objects.none()
        workspace = resolve_active_workspace(self.request)
        # select_related: AlertSerializer reads strategy.name for every row.
        qs = Alert.objects.filter(workspace=workspace).select_related("strategy")
        unread = self.request.query_params.get("unread")
        if unread in ("1", "true", "True"):
            qs = qs.filter(is_read=False)
        return qs

    @extend_schema(request=None, responses=AlertSerializer)
    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        alert = self.get_object()
        alert.is_read = True
        alert.save(update_fields=["is_read"])
        return Response(self.get_serializer(alert).data)

    @extend_schema(request=None, responses=inline_serializer(
        name="MarkAllReadResponse", fields={"updated": rf_serializers.IntegerField()},
    ))
    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        """One UPDATE for the whole workspace — no read-modify-write race, and
        alerts that arrive after the statement snapshots stay unread."""
        workspace = resolve_active_workspace(request)
        updated = Alert.objects.filter(workspace=workspace, is_read=False).update(is_read=True)
        return Response({"updated": updated})

    @extend_schema(responses=inline_serializer(
        name="UnreadCountResponse", fields={"unread": rf_serializers.IntegerField()},
    ))
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        """Cheap badge endpoint: an indexed COUNT, no serialization."""
        workspace = resolve_active_workspace(request)
        count = Alert.objects.filter(workspace=workspace, is_read=False).count()
        return Response({"unread": count})
