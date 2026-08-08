import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient

from core.models import Workspace


@pytest.fixture(autouse=True)
def clear_cache():
    """The eval lock lives in the (process-wide LocMem) cache in tests; clear it
    between tests so a lock can never leak from one test into the next."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="trader", email="trader@example.com", password="pw12345!"
    )


@pytest.fixture
def workspace(user):
    return Workspace.objects.create(name="Desk", owner=user)


@pytest.fixture
def auth_client(user, workspace):
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    client.defaults["HTTP_X_WORKSPACE_ID"] = str(workspace.id)
    return client
