from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    StrategyViewSet,
    AlertViewSet,
    MarketAnalysisView,
    IndicatorCatalogView,
)

router = DefaultRouter()
router.register(r"strategies", StrategyViewSet, basename="strategy")
router.register(r"alerts", AlertViewSet, basename="alert")

urlpatterns = [
    path("indicators/", IndicatorCatalogView.as_view(), name="indicator-catalog"),
    path("markets/<str:ticker>/analysis/", MarketAnalysisView.as_view(), name="market-analysis"),
    *router.urls,
]
