from rest_framework.routers import DefaultRouter

from .views import StrategyViewSet, AlertViewSet

router = DefaultRouter()
router.register(r"strategies", StrategyViewSet, basename="strategy")
router.register(r"alerts", AlertViewSet, basename="alert")

urlpatterns = router.urls
