from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from common.health import HealthView
from identity.views import LogoutView, RegisterView

urlpatterns = [
    path("admin/", admin.site.urls),

    # Infra probe (load balancers / uptime monitors) — outside /api/v1.
    path("healthz/", HealthView.as_view(), name="healthz"),

    # Authentication (stateless JWT)
    path("api/v1/auth/register/", RegisterView.as_view(), name="register"),
    path("api/v1/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/v1/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # Blacklists the submitted refresh token so "log out" revokes the session
    # server-side instead of only clearing the client's storage.
    path("api/v1/auth/logout/", LogoutView.as_view(), name="logout"),

    # One include per feature; each app owns its own routes.
    path("api/v1/", include("identity.urls")),    # workspaces, account limits
    path("api/v1/", include("watchlist.urls")),   # watchlist + compiled stock pages
    path("api/v1/", include("markets.urls")),     # indicator catalog, market analysis
    path("api/v1/", include("strategies.urls")),  # strategies, alerts

    # OpenAPI
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
