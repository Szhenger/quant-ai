from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.workspaces import resolve_active_workspace
from marketdata import INDICATOR_SPECS, OPERATORS, analyze_market
from .models import Strategy, Alert
from .serializers import StrategySerializer, AlertSerializer
from .compiler import compile_graph, GraphCompilationError


class StrategyViewSet(viewsets.ModelViewSet):
    """CRUD for user-defined market-monitoring strategies, scoped to the active workspace."""

    serializer_class = StrategySerializer

    def get_queryset(self):
        workspace = resolve_active_workspace(self.request)
        return Strategy.objects.filter(workspace=workspace)

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
            "indicator": compiled["indicator"],
            "params": compiled["params"],
            "operator": compiled["operator"],
            "threshold": compiled["threshold"],
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


class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AlertSerializer

    def get_queryset(self):
        workspace = resolve_active_workspace(self.request)
        qs = Alert.objects.filter(workspace=workspace)
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


class MarketAnalysisView(APIView):
    """Quantitative snapshot for a ticker: price series + all indicators."""

    def get(self, request, ticker):
        # Ensure the request is workspace-scoped (auth + tenant boundary).
        resolve_active_workspace(request)
        try:
            days = int(request.query_params.get("days", 180))
        except ValueError:
            days = 180
        days = max(30, min(days, 730))
        return Response(analyze_market(ticker.upper(), days=days))


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
