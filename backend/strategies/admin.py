from django.contrib import admin

from .models import Strategy, Alert


@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    list_display = ("name", "ticker", "indicator", "operator", "threshold",
                    "status", "last_triggered_at")
    list_filter = ("status", "indicator", "ai_enabled")
    search_fields = ("name", "ticker")


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("ticker", "indicator", "metric_value", "ai_used", "is_read", "created_at")
    list_filter = ("is_read", "ai_used", "indicator")
    search_fields = ("ticker",)
