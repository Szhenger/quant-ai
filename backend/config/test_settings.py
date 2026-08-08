"""Test settings: sqlite, eager Celery, in-memory channels, no external services."""
from .settings import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

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

# Disable throttling in tests.
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": [], "DEFAULT_THROTTLE_RATES": {}}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
