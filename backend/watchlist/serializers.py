from rest_framework import serializers

from .models import WatchedTicker, StockPage


class WatchedTickerSerializer(serializers.ModelSerializer):
    # Read-only page freshness so the list can show "last updated" without a
    # second request. ``refresh_interval_hours`` (n) and
    # ``recompute_interval_hours`` (m) are client-settable per ticker.
    refreshed_at = serializers.DateTimeField(source="page.refreshed_at", read_only=True)
    recomputed_at = serializers.DateTimeField(source="page.recomputed_at", read_only=True)
    has_page = serializers.SerializerMethodField()

    class Meta:
        model = WatchedTicker
        fields = (
            "id", "ticker", "note",
            "refresh_interval_hours", "recompute_interval_hours",
            "refreshed_at", "recomputed_at", "has_page", "created_at",
        )
        read_only_fields = ("id", "created_at", "refreshed_at", "recomputed_at", "has_page")

    def get_has_page(self, obj) -> bool:
        try:
            return obj.page is not None
        except StockPage.DoesNotExist:
            return False

    def validate(self, attrs):
        # The (workspace, ticker) unique constraint can't be auto-validated by DRF
        # because workspace isn't a serializer field — without this check a
        # duplicate add surfaces as a 500 IntegrityError instead of a 400.
        from common.validators import normalize_ticker

        ticker = attrs.get("ticker", getattr(self.instance, "ticker", ""))
        try:
            ticker = normalize_ticker(ticker)
        except ValueError as exc:
            raise serializers.ValidationError({"ticker": str(exc)}) from exc
        if "ticker" in attrs:
            attrs["ticker"] = ticker
        request = self.context.get("request")
        if request is not None and ticker:
            from identity.workspaces import resolve_active_workspace

            workspace = resolve_active_workspace(request)
            qs = WatchedTicker.objects.filter(workspace=workspace, ticker=ticker)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"ticker": f"{ticker} is already on this watchlist."}
                )
        return attrs


class StockPageSerializer(serializers.ModelSerializer):
    """The compiled stock page: both measures, each in detailed + summarised form."""

    ticker = serializers.CharField(source="watched_ticker.ticker", read_only=True)
    refresh_interval_hours = serializers.IntegerField(
        source="watched_ticker.refresh_interval_hours", read_only=True
    )
    recompute_interval_hours = serializers.IntegerField(
        source="watched_ticker.recompute_interval_hours", read_only=True
    )

    class Meta:
        model = StockPage
        fields = (
            "ticker",
            "quantitative", "quantitative_summary",
            "qualitative", "qualitative_summary",
            "data_synthetic", "refreshed_at", "recomputed_at",
            "refresh_interval_hours", "recompute_interval_hours",
        )
        read_only_fields = fields
