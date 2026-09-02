from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

from .models import Workspace

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
