# QuantAI — Backend

Django 5 + DRF + Channels + Celery. Serves the API, the live-alert WebSocket, and the
strategy-evaluation worker fleet.

## Apps / packages
- `core` — `Workspace` (tenant) + `WatchedTicker`, JWT registration, workspace resolver.
- `marketdata` — price providers (`yfinance` + deterministic synthetic fallback) and the
  numpy indicator library (`compute_indicator`, `evaluate_condition`, `analyze_market`).
- `ai` — `ClaudeClient.assess` (Anthropic), degrades gracefully with no API key.
- `strategies` — `Strategy` + `Alert` models, CRUD + graph-deploy + market-analysis API,
  the Celery tasks (`sweep_due_strategies`, `evaluate_strategy`), alert `delivery`, and the
  `AlertConsumer` WebSocket (+ JWT WS auth in `ws_auth.py`).
- `config` — settings, URLs, ASGI (Channels routing), Celery app.

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional; sensible defaults otherwise
python manage.py migrate
daphne -b 0.0.0.0 -p 8000 config.asgi:application   # HTTP + WebSockets

# scheduled evaluation (separate shells):
celery -A config worker -l info
celery -A config beat -l info
```

Requires Python 3.10+ (Django 5). Postgres + Redis for full operation; the test suite
needs neither.

## Test

```bash
pytest        # config.test_settings: sqlite, eager Celery, in-memory Channels, synthetic data
```

## Key environment variables
See `.env.example`. Notably: `MARKETDATA_PROVIDER` (`auto`/`yfinance`/`synthetic`),
`ANTHROPIC_API_KEY` (enables the AI layer), `REDIS_URL`, and the `DB_*` connection vars.
