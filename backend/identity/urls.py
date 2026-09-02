from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import LimitsView, WorkspaceViewSet

router = DefaultRouter()
router.register(r"workspaces", WorkspaceViewSet, basename="workspace")

urlpatterns = [
    path("limits/", LimitsView.as_view(), name="account-limits"),
    *router.urls,
]
