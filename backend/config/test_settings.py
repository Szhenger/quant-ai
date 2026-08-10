"""Test settings: PostgreSQL (prod parity), eager Celery, in-memory channels.

The database is the ONE external service tests use: running the suite on the
same engine as production means SELECT FOR UPDATE, duration arithmetic and
JSONB behave for real instead of being silently no-op'd by sqlite.

DATABASES is inherited from base settings (DB_HOST/DB_PORT/DB_USER/... env
vars); pytest-django creates and destroys an isolated ``test_<DB_NAME>``
database around the run. Locally: ``docker compose up -d db`` from the repo
root, or run the whole suite in a container via
``docker compose -f docker-compose.test.yml run --rm --build test``.
"""
from .settings import *  # noqa: F401,F403

# Run Celery tasks inline, surface exceptions.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# In-memory channel layer (no Redis needed for tests).
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# Local-memory cache for tests (tests are single-process, so the eval lock still
# behaves correctly). A per-test cache.clear() fixture keeps locks from leaking.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Deterministic, offline market data.
MARKETDATA_PROVIDER = "synthetic"

# No real LLM calls in tests; ClaudeClient degrades gracefully with no key.
ANTHROPIC_API_KEY = ""

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Disable throttling in tests. Scoped throttles are attached per-view, so their
# scopes must still exist here — a None rate disables the throttle.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {
        "anon": None, "user": None, "evaluate": None, "replay": None, "analysis": None,
    },
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
