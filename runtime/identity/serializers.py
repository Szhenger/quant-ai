from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

from .models import Workspace, WatchedTicker

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ("id", "username", "email", "password")

    def create(self, validated_data):
        # Atomic: a failure creating the default workspace must roll back the
        # user too — every account is born usable, never workspace-less.
        with transaction.atomic():
            user = User.objects.create_user(
                username=validated_data["username"],
                email=validated_data.get("email", ""),
                password=validated_data["password"],
            )
            # Every user starts with a default workspace so the app is usable immediately.
            Workspace.objects.create(name="My Workspace", owner=user)
        return user


class WorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = ("id", "name", "created_at")
        read_only_fields = ("id", "created_at")


class WatchedTickerSerializer(serializers.ModelSerializer):
    class Meta:
        model = WatchedTicker
        fields = ("id", "ticker", "note", "created_at")
        read_only_fields = ("id", "created_at")

    def validate(self, attrs):
        # The (workspace, ticker) unique constraint can't be auto-validated by DRF
        # because workspace isn't a serializer field — without this check a
        # duplicate add surfaces as a 500 IntegrityError instead of a 400.
        from .validators import normalize_ticker

        ticker = attrs.get("ticker", getattr(self.instance, "ticker", ""))
        try:
            ticker = normalize_ticker(ticker)
        except ValueError as exc:
            raise serializers.ValidationError({"ticker": str(exc)}) from exc
        if "ticker" in attrs:
            attrs["ticker"] = ticker
        request = self.context.get("request")
        if request is not None and ticker:
            from .workspaces import resolve_active_workspace

            workspace = resolve_active_workspace(request)
            qs = WatchedTicker.objects.filter(workspace=workspace, ticker=ticker)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"ticker": f"{ticker} is already on this watchlist."}
                )
        return attrs
