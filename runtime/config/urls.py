from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from identity.views import HealthView, LogoutView, RegisterView

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

    # Workspaces + watchlist
    path("api/v1/", include("identity.urls")),

    # Strategies, alerts, market analysis
    path("api/v1/", include("engine.urls")),

    # OpenAPI
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
