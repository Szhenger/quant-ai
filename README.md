# QuantAI

An AI-powered quantitative-research workspace. Follow the markets you care about,
get their quantitative analysis on demand, define the exact conditions you want to
watch for, and receive **AI-contextualised alerts** the moment those conditions fire.

QuantAI packages the day-to-day of a quant researcher into three moves:

1. **Follow markets** — build a watchlist and pull a live quantitative snapshot
   (z-score, RSI, MACD, moving-average spread, volatility, % change) for any ticker.
2. **Define conditions** — create a strategy such as *"AAPL 20-day z-score < −2"*
   with an optional AI directive (*"is the earnings thesis actually broken?"*).
3. **Get alerted** — the system evaluates active strategies on a schedule, asks
   Claude whether a triggered condition is a real signal or noise, and delivers an
   alert in-app (live WebSocket), by email, and/or to a webhook.

---

## Architecture

```
                     ┌──────────────────────────────────────────────┐
  React SPA  ──HTTP──▶  Django + DRF API  (auth, workspaces, CRUD)   │
   (Vite)    ──WS────▶  Django Channels    (live alert stream)       │
                     └───────────────┬──────────────────────────────┘
                                     │
              Celery Beat (every 60s)│ sweep_due_strategies
                                     ▼
                        Celery worker: evaluate_strategy
                   ┌───────────────┼─────────────────┐
                   ▼               ▼                 ▼
             market data      quant indicators   Claude (AI)
           (yfinance / synth)  (numpy)          contextualisation
                                     │
                                     ▼
                          Alert  ──▶  in-app / email / webhook
```

- **`backend/`** — Django 5 + DRF + Channels + Celery.
  - `core` — `Workspace` (tenant) + `WatchedTicker` watchlist, JWT auth, registration.
  - `marketdata` — pluggable price providers (yfinance with a deterministic synthetic
    fallback) and a numpy indicator library.
  - `ai` — Anthropic Claude client with graceful degradation (no key → fire on the
    quantitative condition alone).
  - `strategies` — `Strategy` + `Alert` models, CRUD API, React-Flow graph compiler,
    the evaluation Celery tasks, alert delivery, and the WebSocket consumer.
- **`frontend/`** — React + TypeScript + Vite SPA (strategy form builder **and** a
  React-Flow node-graph builder, market-analysis dashboard, live alerts panel).

Multi-tenancy is enforced at the application layer: every workspace-scoped request
must carry an `X-Workspace-ID` header, and querysets are filtered to workspaces the
authenticated user owns. WebSocket connections authenticate via a JWT `?token=` query
parameter and are refused if the user does not own the requested workspace.

---

## Quickstart (Docker)

```bash
docker compose up --build        # starts postgres, redis, api (ASGI), worker, beat
```

The API is then at `http://localhost:8000` (`/api/docs/` for the OpenAPI UI).

Run the frontend against it:

```bash
cd frontend
npm install
npm run dev                      # http://localhost:5173 (proxies /api and /ws to :8000)
```

Set `ANTHROPIC_API_KEY` in your environment (or `backend/.env`) to enable the AI
layer; without it, alerts fire on the quantitative condition alone.

## Quickstart (local, no Docker)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export MARKETDATA_PROVIDER=synthetic          # or 'auto' to use live yfinance data
python manage.py migrate
python manage.py runserver                    # dev; use daphne for WebSockets
# in another shell, for scheduled evaluation:
celery -A config worker -l info
celery -A config beat -l info
```

> The dev `runserver` serves HTTP only. For live WebSocket alerts run the ASGI server:
> `daphne -b 0.0.0.0 -p 8000 config.asgi:application`.

---

## Tests

```bash
cd backend
pip install -r requirements.txt
pytest                 # 33 tests: indicators, compiler, API, tenant isolation, evaluation
```

Tests run fully offline: sqlite, eager Celery, in-memory Channels, the synthetic
market-data provider, and the AI layer in its no-key degradation mode.

---

## The strategy → evaluate → alert loop

1. A user POSTs a strategy (form builder) or a node graph (`/strategies/deploy-graph/`).
2. `Strategy` is persisted, bound to the active workspace, `status=active`.
3. `sweep_due_strategies` (Beat, 60s) enqueues `evaluate_strategy` for every active
   strategy whose `poll_interval_minutes` has elapsed.
4. `evaluate_strategy` pulls prices → computes the indicator → checks the operator/threshold
   (with cross-over support) → respects the cooldown → optionally asks Claude to confirm
   the signal → creates an `Alert` and delivers it across the opted-in channels.

See `docs/architecture.md` for the full design and `docs/api.md` for the endpoint reference.
