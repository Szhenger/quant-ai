from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Workspace, WatchedTicker

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ("id", "username", "email", "password")

    def create(self, validated_data):
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
