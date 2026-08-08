from rest_framework.routers import DefaultRouter

from .views import WorkspaceViewSet, WatchedTickerViewSet

router = DefaultRouter()
router.register(r"workspaces", WorkspaceViewSet, basename="workspace")
router.register(r"watchlist", WatchedTickerViewSet, basename="watchlist")

urlpatterns = router.urls
