# QuantAI — Backend (the engine room)

This is the machine the [course](../README.md) is about. Django 5 on ASGI, wrapped by
Channels and Celery, it does three jobs at once: it **serves the API** (the contract of
[Chapter 9](../documentation/09-the-api-contract.md)), it **pushes live alerts** down a WebSocket,
and it runs a **fleet of workers** that evaluate your strategies on a schedule and fire
alerts exactly once. Everything runs **offline** against a deterministic synthetic market,
so you can hack on it with no API key and no internet — the same property that makes every
worked example in the docs reproducible on your laptop.

If the docs are the *why*, this README is the *where*: a map of the code and the commands
to run it.

## The map — apps, and the chapters that explain them

Each app is a package under `backend/`. Where it implements math or ideas the course
teaches, the chapter is your reference.

| App | What it is | Where the ideas live |
|---|---|---|
| `identity` | Who you are and what you may spend. The `Workspace` (the tenancy unit), JWT registration/logout, `resolve_active_workspace` — the one line that enforces "this workspace is really yours" — and the account guards (`limits.py`: the strategy cap and the deploy-time cost estimate, exposed at `GET /limits/`). | [Ch. 8](../documentation/08-from-math-to-system.md) (isolation), [Ch. 9](../documentation/09-the-api-contract.md) (the header check) |
| `markets` | The numbers. Price providers (`yfinance` + the deterministic synthetic fallback, wrapped by the two bar caches), the numpy indicator library and the field registry (`indicators.py`), composite condition trees + signal replay (`conditions.py`), and the two read endpoints (`GET /markets/<t>/analysis/`, `GET /indicators/`). Every z-score, SMA, RSI, and volatility figure is born here. | [Chapters 1–6](../README.md#the-syllabus) |
| `watchlist` | The stock pages. `WatchedTicker` + its compiled `StockPage` (a quantitative measure over a macro window and a qualitative measure of this week's news, each detailed + summarised), the pure builders (`stockpage.py`), the Celery tasks that compile on the n/m cadences and keep compressed `QuantSnapshot`s for continuity, and the `/watchlist/` API. | [Ch. 8](../documentation/08-from-math-to-system.md) |
| `strategies` | The system. `Strategy` + `Alert` models, the CRUD / graph-deploy / replay API, the `AlertConsumer` WebSocket (+ JWT WS auth in `ws_auth.py`), and — the beating heart — `tasks.py`: `sweep_due_strategies` and `evaluate_strategy`, plus alert delivery (`delivery.py`) and reconciliation. | The API in [Ch. 9](../documentation/09-the-api-contract.md); `tasks.py` in [Ch. 8](../documentation/08-from-math-to-system.md) & [Ch. 10 — Concurrency & safety](../documentation/10-concurrency-and-safety.md) |
| `advisor` | The doubt layer. `ClaudeClient.assess` asks Claude whether a raw signal is worth bothering you about, `summarize_news` writes the stock page's briefing, and both **degrade gracefully to a no-op with no API key** — so the offline path never blocks. `budget.py` meters the paid calls per user per day. | [Ch. 7 — Signal vs. noise](../math/07-signal-vs-noise.md) |
| `common` | What every feature shares and none owns: the single-flight compute cache + ETag helpers behind the interactive read path (`caching.py`, below), input validators (ticker shape, webhook SSRF check), the workspace event bus (`events.py`), and the health probe. | [Ch. 10](../documentation/10-concurrency-and-safety.md) (the stampede) |
| `config` | The wiring. `settings.py`, URL routing (one `include` per feature app), `asgi.py` (where HTTP and WebSocket protocols split), and the Celery app + beat schedule. | [Ch. 8](../documentation/08-from-math-to-system.md) |

Dependencies run one way: `strategies` and `watchlist` import from `markets`, `identity`,
`advisor` and `common`; `markets` and `identity` import only from `common` (and `identity.limits`
from `advisor.budget`); `common` and `advisor` import nothing of ours. Two Django labels are
historical (`identity` is `core`, and the watchlist tables keep their `core_*` names via
`db_table`) so the migration history reads straight through the reorganizations.

> **Short:** if you only open one file, make it `strategies/tasks.py`. It's where a formula
> becomes a service, and where "send the alert *once*" is either won or lost. Read
> [Chapter 10](../documentation/10-concurrency-and-safety.md) with that file open.

## The interactive read path (performance & concurrency)

The worker fleet has its own concurrency story (Ch. 10); the web tier has one too, and it
lives in `common/caching.py` + the two views that use it (`markets/views.py`, the replay action in `strategies/views.py`):

- **Single-flight compute cache.** `GET /markets/<t>/analysis/` and `/strategies/<id>/replay/`
  are pure functions of their inputs plus the provider's bars, so the finished payload is
  cached fleet-wide in Redis. The subtle part is the *stampede*: when a hot key expires,
  every concurrent request would recompute at once. `cached_compute` takes a flight lock
  (`cache.add`, the same atomic primitive as the eval lock); within a process, Django's ASGI
  handler already serializes sync views onto one thread, so in-process stampedes can't happen
  at all. When the flight is held by *another* process we deliberately compute anyway rather
  than sleep-wait — on that shared thread, a sleeping request would block every other request
  in its process, which is far worse than one duplicate computation (waiting is opt-in via
  `wait_budget` for callers that own their thread, like Celery workers). Replay keys are
  **content-addressed** (condition tree + ticker + window, *not* strategy id), so identical
  conditions share one entry. Payloads computed from **synthetic fallback data** are cached
  only briefly (`SYNTHETIC_CACHE_TTL`), so a connectivity blip never pins fabricated numbers
  for the full TTL.
- **Conditional GET.** Both endpoints send a strong `ETag`; a matching `If-None-Match` gets
  an empty `304` — revalidation costs a hash compare, not a recompute or a re-download.
- **Gzip.** Indicator/replay payloads are large, repetitive JSON; `GZipMiddleware` cuts them
  ~5–10× on the wire.
- **Cursor pagination for alerts.** The one table that grows forever is paged by keyset
  (`created_at`, backed by a composite index), so page 100 costs the same as page 1 and
  concurrent inserts can't shift the window mid-walk. `unread-count` is an indexed `COUNT`;
  `mark-all-read` is a single `UPDATE` (no read-modify-write race).
- **Scoped throttle.** The compute-heavy endpoints (`analysis`, `replay`, manual `evaluate`)
  carry a separate `compute` rate on top of the global user throttle.

## Run it locally (no Docker)

You need **Python 3.10+** (the project is on Django 5). Postgres + Redis are needed for the
*full* live system — the API, the WebSocket, and the scheduled worker fleet — but not for the
tests (see below).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # loaded automatically; sets DJANGO_DEBUG=True for local dev
python manage.py migrate

# The ASGI server: serves both HTTP and WebSockets on :8000
daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

Then, in two more shells, the evaluation fleet — a worker to *do* the evaluations and a beat
scheduler to *trigger* them once a minute:

```bash
celery -A config worker -l info   # runs evaluate_strategy jobs
celery -A config beat   -l info   # sweeps due strategies every 60s
```

That's the whole live system: `daphne` is the door and the pipe, the worker is the muscle,
beat is the heartbeat. (Prefer one command? `docker compose -f runtime/docker-compose.yml up --build` from the repo root
brings up Postgres, Redis, and all three.)

## Test it (offline, except the database)

The suite lives at the repo root in [`test/backend/`](../test/README.md) (`backend/test`
is a symlink to it, so `cd backend && pytest` still works), and the
[`test/qtest`](../test/README.md) runner selects suites by behavior area.

The tests run against **PostgreSQL** — the same engine as production, so row locking and
duration arithmetic are exercised for real. Everything else stays hermetic: a dedicated
`config.test_settings` runs Celery **eagerly** (tasks execute inline, no broker), uses an
in-memory channel layer, and forces the **synthetic** market.

```bash
docker compose -f runtime/docker-compose.yml up -d db   # from the repo root: the throwaway Postgres
cd backend && pytest      # pytest-django creates/destroys test_quantai around the run

# Or run the whole suite in a container (starts its own test-db):
docker compose -f runtime/docker-compose.test.yml run --rm --build test
```

The tests double as a guided tour of the engine: `test_indicators.py` checks the
Chapter 1–6 math, `test_evaluation.py` and `test_compiler.py` exercise the strategy pipeline,
`test_api.py` walks the Chapter 9 contract end to end, and `test_webstack.py` covers the
web tier's performance/concurrency behavior (single-flight caching, ETags, cursor pages,
the WebSocket heartbeat).

## The UX-invariant framework (`test/backend/journeys/`)

On top of the unit and contract layers sits an *experience* layer that keeps future PRs
from silently losing behavior users rely on:

- **`test_user_journeys.py`** — whole sessions in user order (first session, strategy
  lifecycle, hostile client), asserting the promises mid-flow: exactly-once alerting,
  unread-badge arithmetic, synthetic-data honesty, tenancy walls, real logout. A PR that
  intentionally changes one of these promises must change the assertion in the same commit.
- **`test_contract_fixtures.py` + `fixtures/*.json`** — golden wire-shape samples shared
  with the frontend. This side proves the live API matches them key-for-key;
  `test/frontend/contract/contracts.test.ts` proves `types.ts` matches the *same files* at compile
  time. Changing a serializer therefore fails here → you update the fixture → the frontend
  stops compiling until `types.ts` and its key map are updated too. The contract cannot
  drift on one side only.
- **`uxspec.py`** — `ConsoleClient` (drives the API exactly as `frontend/src/api/client.ts`
  does) and the shared invariant assertions.

## Key environment variables

Everything has a working default; you rarely need to set anything to run offline. The ones
that matter (full list in `.env.example`):

| Variable | Default | What it does |
|---|---|---|
| `MARKETDATA_PROVIDER` | `auto` | `auto` uses `yfinance` when it's importable/online, else falls back to `synthetic`. Force `synthetic` for reproducible, offline data; `yfinance` for real quotes. |
| `ANALYSIS_CACHE_TTL` / `REPLAY_CACHE_TTL` | `120` / `600` | Seconds the finished analysis/replay payloads live in the fleet-wide compute cache (`common/caching.py`). Analysis is an intraday snapshot (short); a replay only changes when the day rolls or the condition tree does (longer). |
| `SYNTHETIC_CACHE_TTL` | `30` | Seconds a payload computed from synthetic *fallback* data may live in that cache — kept short so real data replaces it as soon as connectivity returns. |
| `ANTHROPIC_API_KEY` | *(empty)* | **Optional.** Set it to switch on the real Chapter 7 AI layer; leave it empty and `ai` degrades to a no-op. No key needed to learn. |
| `REDIS_URL` | `redis://localhost:6379/0` | Backs Channels (alert delivery), the Celery broker/result store, **and** the shared cache that holds the per-strategy evaluation lock ([Ch. 10](../documentation/10-concurrency-and-safety.md)). Must be a shared backend, not per-process memory. |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | `quantai` / `quantai` / `quantai` / `localhost` / `5432` | The Postgres connection for the live system *and* the tests (which create an isolated `test_<DB_NAME>` database on the same server). |

---

New here? Start with the [course README](../README.md) and read the docs in order — the code
will make far more sense once you know *why* each number exists. Then come back and open
`strategies/tasks.py`.
