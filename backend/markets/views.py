"""The two read-only market endpoints: on-demand analysis and the indicator catalog."""
from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from common.caching import cached_compute, conditional_response, provenance_ttl, stable_key
from common.validators import normalize_ticker
from identity.workspaces import resolve_active_workspace
from . import INDICATOR_SPECS, OPERATORS, analyze_market


class MarketAnalysisView(APIView):
    """Quantitative snapshot for a ticker: price series + all indicators."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "analysis"

    @extend_schema(
        parameters=[OpenApiParameter("days", int, description="History window, 30-730 bars.")],
        responses=OpenApiTypes.OBJECT,
        operation_id="market_analysis",
    )
    def get(self, request, ticker):
        # Ensure the request is workspace-scoped (auth + tenant boundary).
        resolve_active_workspace(request)
        try:
            days = int(request.query_params.get("days", 180))
        except ValueError:
            days = 180
        days = max(30, min(days, 730))
        # Same shape rule as strategies/watchlist: arbitrary path strings must
        # not reach the upstream provider or become shared cache keys.
        try:
            symbol = normalize_ticker(ticker)
        except ValueError as exc:
            raise ValidationError({"ticker": str(exc)})

        # Market analysis is a pure function of public market data — the cache
        # is deliberately shared across users and workspaces.
        key = stable_key("analysis", {
            "ticker": symbol,
            "days": days,
            "provider": settings.MARKETDATA_PROVIDER,
        })
        payload, _ = cached_compute(
            key, provenance_ttl(settings.ANALYSIS_CACHE_TTL),
            lambda: analyze_market(symbol, days=days),
        )
        return conditional_response(request, payload)


class IndicatorCatalogView(APIView):
    """Metadata driving the strategy-builder UI: available indicators + operators."""

    @extend_schema(responses=OpenApiTypes.OBJECT, operation_id="indicator_catalog")
    def get(self, request):
        payload = {
            "indicators": [
                {"key": k, "label": v["label"], "unit": v["unit"],
                 "defaults": v["defaults"],
                 "default_threshold": v.get("default_threshold"),
                 "help": v["help"],
                 # Field-registry metadata: which fields lead a summary, and
                 # the reading bands, so the console words a value exactly
                 # as the stock page does (same bands, same text).
                 "summary": bool(v.get("summary")),
                 "readings": v.get("readings", [])}
                for k, v in INDICATOR_SPECS.items()
            ],
            "operators": [{"key": k, "label": v} for k, v in OPERATORS.items()],
        }
        # Static per-deploy metadata: max-age lets the browser reuse it across
        # page loads without a request; after expiry the ETag turns the
        # revalidation into an empty 304. Changes only ship with a deploy, so
        # an hour of staleness is harmless.
        return conditional_response(request, payload, max_age=3600)
