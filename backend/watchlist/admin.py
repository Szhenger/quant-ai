from django.contrib import admin

from .models import WatchedTicker, StockPage, QuantSnapshot


@admin.register(WatchedTicker)
class WatchedTickerAdmin(admin.ModelAdmin):
    list_display = ("ticker", "workspace", "refresh_interval_hours",
                    "recompute_interval_hours", "created_at")
    list_filter = ("refresh_interval_hours", "recompute_interval_hours")
    search_fields = ("ticker",)


@admin.register(StockPage)
class StockPageAdmin(admin.ModelAdmin):
    list_display = ("watched_ticker", "data_synthetic", "refreshed_at", "recomputed_at")
    list_filter = ("data_synthetic",)
    search_fields = ("watched_ticker__ticker",)


@admin.register(QuantSnapshot)
class QuantSnapshotAdmin(admin.ModelAdmin):
    list_display = ("watched_ticker", "taken_at")
    search_fields = ("watched_ticker__ticker",)
