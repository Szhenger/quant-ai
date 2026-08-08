from django.contrib import admin

from .models import Workspace, WatchedTicker


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")
    search_fields = ("name", "owner__username")


@admin.register(WatchedTicker)
class WatchedTickerAdmin(admin.ModelAdmin):
    list_display = ("ticker", "workspace", "created_at")
    search_fields = ("ticker",)
