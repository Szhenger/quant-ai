from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient

from identity.models import Workspace

# --------------------------------------------------------------------------- #
# Focus-area markers (registered in backend/pytest.ini), applied automatically.
#
# The tree is organized by FEATURE (identity, markets, watchlist, strategies —
# one directory per backend app), plus two cross-feature directories:
# ``system/`` for the invariants that span every app (REST sweep, Celery/Redis
# semantics, storage, the web stack, the event bus) and ``journeys/`` for whole
# user sessions. Markers name the BEHAVIOR AREA a test proves, which is what the
# qtest runner selects on — so a feature directory maps to one marker, and each
# file under system/ names its own.
# --------------------------------------------------------------------------- #
_DIR_MARKERS = {
    "identity": "rest",
    "markets": "indicators",
    "watchlist": "celery_redis",
    "strategies": "celery_redis",
    "journeys": "journeys",
}
_SYSTEM_FILE_MARKERS = {
    "test_api.py": "rest",
    "test_contracts.py": "rest",
    "test_rest_components.py": "rest",
    "test_webstack.py": "rest",
    "test_celery_redis.py": "celery_redis",
    "test_events.py": "celery_redis",
    "test_postgres.py": "postgres",
}


def pytest_collection_modifyitems(items):
    here = Path(__file__).parent
    for item in items:
        try:
            parts = Path(str(item.fspath)).resolve().relative_to(here.resolve()).parts
        except ValueError:
            continue
        top = parts[0]
        marker = _SYSTEM_FILE_MARKERS.get(parts[-1]) if top == "system" else _DIR_MARKERS.get(top)
        if marker is None:
            # A test no suite would ever select is a test that silently never
            # runs under qtest — refuse to collect it until it is classified.
            raise pytest.UsageError(
                f"{'/'.join(parts)} has no focus-area marker: add its directory to "
                "_DIR_MARKERS or, under system/, its filename to _SYSTEM_FILE_MARKERS "
                "(test/backend/conftest.py)."
            )
        item.add_marker(getattr(pytest.mark, marker))


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
