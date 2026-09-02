from django.urls import path

from .views import IndicatorCatalogView, MarketAnalysisView

urlpatterns = [
    path("indicators/", IndicatorCatalogView.as_view(), name="indicator-catalog"),
    path("markets/<str:ticker>/analysis/", MarketAnalysisView.as_view(), name="market-analysis"),
]
