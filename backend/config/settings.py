"""
Django settings for the QuantAI workspace backend.

QuantAI is an AI-powered quantitative-research workspace. Users follow financial
markets, define quantitative conditions on them (e.g. "AAPL 20-day z-score < -2"),
and receive AI-contextualised alerts when those conditions fire.
"""
import os
from pathlib import Path
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from ``path`` into the environment (real environment
    variables win). The README documents `cp .env.example .env` as the local
    setup step, so the file must actually be read — there is no external
    dotenv dependency to forget."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


# --- Core security -----------------------------------------------------------
# Safe-by-default: an unset DJANGO_DEBUG means production behaviour. Local dev
# sets DJANGO_DEBUG=True explicitly (.env.example, docker-compose.yml do).
_DEV_SECRET_KEY = "dev-insecure-key-change-in-production"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _DEV_SECRET_KEY)
DEBUG = env_bool("DJANGO_DEBUG", False)
# The test settings never serve traffic — `pytest` / `make test` must keep
# working with no env exported, so the guard exempts them.
_IS_TEST_RUN = os.environ.get("DJANGO_SETTINGS_MODULE", "").endswith("test_settings")
if not DEBUG and not _IS_TEST_RUN and SECRET_KEY == _DEV_SECRET_KEY:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "Refusing to start with the published dev SECRET_KEY outside DEBUG. "
        "Set DJANGO_SECRET_KEY, or set DJANGO_DEBUG=True for local development."
    )
# 0.0.0.0 is a bind address, never a legitimate client Host header — keep the
# default allowlist tight.
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

if not DEBUG:
    # Deployments terminate TLS at a proxy/load balancer (Render, etc.); trust
    # its forwarded-proto header so request.is_secure() and secure cookies work.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # Belt-and-braces behind the TLS-terminating proxy: if a plaintext request
    # ever reaches Django directly, redirect instead of serving it (a Bearer
    # token on http is a leaked token). The health probe stays exempt —
    # internal checkers may hit it without a forwarded-proto header.
    SECURE_SSL_REDIRECT = True
    SECURE_REDIRECT_EXEMPT = [r"^healthz/?$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # HSTS is opt-in via env (a wrong value bricks a domain for its max-age, so
    # it must be a deliberate deployment decision). Start small (e.g. 3600),
    # raise once HTTPS-everywhere is confirmed.
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", False)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Applications ------------------------------------------------------------
INSTALLED_APPS = [
    "daphne",  # ASGI server + runserver override (must precede staticfiles)
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",
    "channels",

    # QuantAI apps (the ones with models or Celery tasks; ``markets``, ``advisor``
    # and ``common`` are plain libraries and need no registration)
    "identity",
    "watchlist",
    "strategies",
]

MIDDLEWARE = [
    # GZip first so it compresses the final response (indicator/replay payloads
    # are large, repetitive JSON — 5-10x smaller on the wire). Django >= 4.2's
    # GZipMiddleware carries built-in BREACH mitigation (random gzip padding).
    "django.middleware.gzip.GZipMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ]},
    },
]

# --- Database ----------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "quantai"),
        "USER": os.environ.get("DB_USER", "quantai"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "quantai"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

# --- Channels (real-time alert delivery) ------------------------------------
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

# --- Cache (shared across api/worker/beat — backs the per-strategy eval lock) -
# MUST be a shared backend (Redis), not per-process LocMem, or the lock that
# serialises strategy evaluation would not be visible across worker processes.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# --- Celery (strategy evaluation fleet) -------------------------------------
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_TRACK_STARTED = True
CELERY_WORKER_CONCURRENCY = int(os.environ.get("CELERY_CONCURRENCY", "4"))
# Hard-stop runaway tasks BELOW the per-strategy eval lock TTL (300s in
# strategies.tasks), so a lock can never expire while its task is still running.
CELERY_TASK_SOFT_TIME_LIMIT = int(os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", "210"))
CELERY_TASK_TIME_LIMIT = int(os.environ.get("CELERY_TASK_TIME_LIMIT", "240"))
# Results expire quickly: nothing reads a stored result except the eager path
# in the manual-evaluate view (which never touches the backend). Without this,
# one sweep result per minute plus one per evaluation accrues in Redis for
# Celery's default 24h — on a small noeviction Redis that is an outage clock.
CELERY_RESULT_EXPIRES = int(os.environ.get("CELERY_RESULT_EXPIRES", "3600"))
CELERY_BEAT_SCHEDULE = {
    "sweep-due-strategies-every-minute": {
        "task": "strategies.tasks.sweep_due_strategies",
        "schedule": 60.0,
    },
    # Delivery reconciliation: re-enqueue channels that never recorded an
    # outcome (worker died between the alert's commit and the fan-out).
    "reconcile-undelivered-alerts": {
        "task": "strategies.tasks.reconcile_undelivered_alerts",
        "schedule": 300.0,
    },
    # Retention: unbounded tables degrade to a stall over months, not days.
    "prune-expired-alerts-daily": {
        "task": "strategies.tasks.prune_expired_alerts",
        "schedule": 24 * 3600.0,
    },
    "flush-expired-tokens-daily": {
        "task": "identity.tasks.flush_expired_tokens",
        "schedule": 24 * 3600.0,
    },
    # Watchlist stock pages: refresh due tickers (qualitative every n hours,
    # macro-quantitative recompute every m hours). The tick is frequent; the
    # per-ticker n/m intervals decide what actually recompiles each pass.
    "refresh-stock-pages": {
        "task": "watchlist.tasks.refresh_stock_pages",
        "schedule": float(os.environ.get("STOCKPAGE_SWEEP_SECONDS", str(30 * 60))),
    },
}

# How long fired alerts are kept before the daily retention job deletes them.
ALERT_RETENTION_DAYS = int(os.environ.get("ALERT_RETENTION_DAYS", "180"))

# --- Watchlist stock pages (the medical-student MVP) -------------------------
# Each watched ticker compiles a "stock page": a qualitative measure (this
# week's news, summarised by Claude) and a quantitative measure (the standard
# indicators over a macro window). Two independent cadences, both client-settable
# per ticker, defaulting from here:
#   n = how often the qualitative/weekly view refreshes (cheap, frequent);
#   m = how often the macro quantitative measure is recomputed. On each recompute
#       the previous measure is retained, gzip-compressed, for continuity.
STOCKPAGE_REFRESH_INTERVAL_HOURS = int(os.environ.get("STOCKPAGE_REFRESH_INTERVAL_HOURS", "6"))   # n
STOCKPAGE_RECOMPUTE_INTERVAL_HOURS = int(os.environ.get("STOCKPAGE_RECOMPUTE_INTERVAL_HOURS", "24"))  # m
# How many compressed prior quantitative measures to keep per ticker.
STOCKPAGE_SNAPSHOT_RETENTION = int(os.environ.get("STOCKPAGE_SNAPSHOT_RETENTION", "30"))
# The qualitative measure covers "this week"; the quantitative measure is macro.
STOCKPAGE_NEWS_WINDOW_DAYS = int(os.environ.get("STOCKPAGE_NEWS_WINDOW_DAYS", "7"))
STOCKPAGE_NEWS_LIMIT = int(os.environ.get("STOCKPAGE_NEWS_LIMIT", "8"))
STOCKPAGE_MACRO_DAYS = int(os.environ.get("STOCKPAGE_MACRO_DAYS", "180"))

# Consecutive evaluation failures before a strategy is auto-paused to FAILED
# (the circuit breaker). Reactivating the strategy re-arms it.
STRATEGY_MAX_CONSECUTIVE_FAILURES = int(
    os.environ.get("STRATEGY_MAX_CONSECUTIVE_FAILURES", "5")
)

# --- Account guards ------------------------------------------------------------
# The two knobs that bound what one account can make the fleet (and the
# operator's Anthropic bill) do. Both are surfaced to the console via
# GET /limits/ so the user sees the cap before hitting it, and every
# strategy carries a cost estimate (evaluations/day, max AI calls/day) so the
# trade-off is visible at deploy time rather than on the invoice.
# Strategies a single workspace may hold (any status). 0 = unlimited.
STRATEGY_MAX_PER_WORKSPACE = int(os.environ.get("STRATEGY_MAX_PER_WORKSPACE", "50"))
# Paid AI calls (alert contextualisation + news summaries) per user per UTC
# day. Exhaustion fails open: alerts still fire on the quantitative condition,
# stock pages fall back to the non-AI summary.
AI_DAILY_CALL_BUDGET = int(os.environ.get("AI_DAILY_CALL_BUDGET", "200"))

# Optional egress proxy for outbound webhook POSTs (e.g. "http://egress:3128").
# Validation resolves and rejects private addresses, but DNS can rebind between
# that check and the connect (TOCTOU) — a filtering proxy closes the residual
# by policing the actual connection. Empty = direct egress (the validated
# default).
WEBHOOK_EGRESS_PROXY = os.environ.get("WEBHOOK_EGRESS_PROXY", "")

# --- REST framework ----------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Bounded: caps client-supplied ?limit= (see config/pagination.py).
    "DEFAULT_PAGINATION_CLASS": "config.pagination.BoundedLimitOffsetPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        # Inert unless a view sets throttle_scope — used by the compute-heavy
        # endpoints (analysis, replay, manual evaluate).
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/hour",
        "user": "2000/hour",
        # Scoped budgets for the expensive endpoints (network + compute heavy):
        "evaluate": "20/min",
        "replay": "30/min",
        "analysis": "120/min",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "QuantAI Workspace API",
    "DESCRIPTION": "Quantitative market monitoring, AI-contextualised alerting, and strategy management.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # drf-spectacular's serve views default to AllowAny, bypassing the
    # project-wide IsAuthenticated: the API surface should not be publicly
    # enumerable.
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
}

CORS_ALLOWED_ORIGINS = os.environ.get(
    "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")
# Every workspace-scoped request carries X-Workspace-ID; without this the
# browser's CORS preflight rejects it for any cross-origin frontend.
from corsheaders.defaults import default_headers  # noqa: E402

CORS_ALLOW_HEADERS = [*default_headers, "x-workspace-id"]

# --- Market data provider ----------------------------------------------------
# auto -> use yfinance when importable/online, else deterministic synthetic data.
MARKETDATA_PROVIDER = os.environ.get("MARKETDATA_PROVIDER", "auto")

# --- Interactive read-path compute cache (common.caching) --------------------
# Fleet-wide (Redis) TTLs for the finished analysis/replay payloads. Short for
# analysis (an intraday snapshot), longer for replay (a function of daily bars
# and the condition tree — it only changes when the day rolls or the tree does).
ANALYSIS_CACHE_TTL = int(os.environ.get("ANALYSIS_CACHE_TTL", "120"))
REPLAY_CACHE_TTL = int(os.environ.get("REPLAY_CACHE_TTL", "600"))
# Payloads computed from synthetic *fallback* data (provider degraded) live
# only briefly, so real data replaces them as soon as connectivity returns.
SYNTHETIC_CACHE_TTL = int(os.environ.get("SYNTHETIC_CACHE_TTL", "30"))

# Optional local bar cache (Parquet files queried with DuckDB). Off by default;
# when on, real bars are cached under MARKETDATA_CACHE_DIR for MARKETDATA_CACHE_TTL
# seconds so repeated evaluations reuse them. Synthetic data is never cached.
MARKETDATA_CACHE = env_bool("MARKETDATA_CACHE", False)
MARKETDATA_CACHE_DIR = os.environ.get("MARKETDATA_CACHE_DIR", str(BASE_DIR / ".marketdata_cache"))
MARKETDATA_CACHE_TTL = int(os.environ.get("MARKETDATA_CACHE_TTL", "3600"))

# Fleet-wide shared bar cache (the Redis-backed default Django cache): N
# strategies evaluating the same ticker cost ONE upstream fetch per TTL window
# across all workers, and a single-flight lock coalesces concurrent fetches.
# The synthetic flag is cached with the bars; synthetic fallbacks get a short
# TTL so real data is retried promptly. Applies to yfinance/auto modes only.
MARKETDATA_SHARED_CACHE = env_bool("MARKETDATA_SHARED_CACHE", True)
MARKETDATA_SHARED_CACHE_TTL = int(os.environ.get("MARKETDATA_SHARED_CACHE_TTL", "300"))
MARKETDATA_SHARED_CACHE_SYNTHETIC_TTL = int(
    os.environ.get("MARKETDATA_SHARED_CACHE_SYNTHETIC_TTL", "30")
)
# Max seconds a coalescing waiter polls for another worker's in-flight fetch
# before giving up and fetching directly.
MARKETDATA_FETCH_WAIT = float(os.environ.get("MARKETDATA_FETCH_WAIT", "10"))

# --- Anthropic Claude (AI contextualisation layer) --------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
ANTHROPIC_TIMEOUT_SECONDS = float(os.environ.get("ANTHROPIC_TIMEOUT_SECONDS", "30"))

# --- Email (SMTP alert channel) ---------------------------------------------
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "10"))
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "alerts@quantai.local")

# --- Misc --------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# In DEBUG, whitenoise serves straight from the app static dirs (no
# collectstatic needed); in production it serves the collected STATIC_ROOT.
WHITENOISE_USE_FINDERS = DEBUG
WHITENOISE_AUTOREFRESH = DEBUG
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
