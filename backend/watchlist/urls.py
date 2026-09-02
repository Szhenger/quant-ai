from rest_framework.routers import DefaultRouter

from .views import WatchedTickerViewSet

router = DefaultRouter()
router.register(r"watchlist", WatchedTickerViewSet, basename="watchlist")

urlpatterns = router.urls
