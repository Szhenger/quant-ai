# The Testing Suite

This folder is the single home of every test in QuantAI — the backend pytest
suite, the frontend vitest suite, the golden contract fixtures they share, and
`qtest`, the runner that selects suites by **behavior area** instead of by
tool. If you want to know whether the application does what it promises, you
start here.

The promise of this README is the same as everywhere else in the repo: nothing
assumed beyond CS50x. By the end you'll know what each layer of the suite
proves, how to run any slice of it, and how the pieces keep *each other*
honest.

---

## The map

```
test/
├── qtest                  # the runner: ./test/qtest run rest postgres …
├── framework/             # qtest's implementation (suite registry + toolchains)
├── backend/               # the pytest suite (Django + Celery + PostgreSQL)
│   ├── conftest.py        #   shared fixtures + directory/file→marker mapping
│   ├── identity/          #   the account guards (strategy cap, AI budget, GET /limits/)
│   ├── markets/           #   quant math, condition trees, replay, providers, both bar caches
│   ├── watchlist/         #   stock-page measures, n/m cadences, continuity snapshots
│   ├── strategies/        #   compiler, evaluation, delivery, the pinned audit regressions
│   ├── system/            #   cross-feature invariants: REST sweep + contracts + web stack,
│   │                      #   Celery/Redis semantics, PostgreSQL behavior, the event bus
│   └── journeys/          #   whole user sessions + the golden fixtures
└── frontend/              # the vitest suite (pure logic, contract pins, rendered components)
    ├── setup.ts           #   jest-dom matchers + unmount after every test
    ├── helpers/           #   the fake wire (axios adapter) and the render/sign-in helpers
    ├── contract/          #   the contract mirrors: types pin, cursor, readings, cost estimate
    ├── realtime/          #   backoff, cache merges, realtime journeys, the socket wrapper
    ├── session/           #   the transport (single-flight refresh), the auth store, the login page
    ├── features/          #   the three panels rendered against the fake wire
    └── app/               #   the shell: session restore, tabs, logout
```

The backend tree mirrors `backend/` one directory per feature app, plus `system/` for the
invariants that span every app and `journeys/` for whole sessions. A test's **directory** says
which feature it belongs to; its **marker** says which behavior area it proves (that is what
`qtest` selects on). Feature directories map to one marker each and every file under `system/`
names its own — the map lives at the top of `backend/conftest.py`.

Two compatibility shims keep every existing entry point working:
`backend/test` is a **symlink** to `test/backend/` (so `cd backend && pytest`
and `pytest.ini`'s `testpaths = test` still collect), and the Docker test
stack **bind-mounts** `test/backend` to `/app/test` (the image itself never
contains tests — see `backend/.dockerignore` and
`runtime/docker-compose.test.yml`).

---

## Running it

The one-command version:

```bash
./test/qtest run                 # the four focus areas (below)
./test/qtest run all             # everything: whole backend + whole frontend
./test/qtest list                # what exists
```

`qtest` figures out which toolchain you have and routes each suite to it:

| You have… | Backend suites run via | Frontend suites run via |
|---|---|---|
| `backend/.venv` + the dev Postgres (`make venv db-init db-start`) | the venv's pytest (fastest) | `npm test` |
| Docker only | `runtime/docker-compose.test.yml` (CI parity) | `npm test` |
| Neither | reported **unavailable** (exit 2) — push and let CI run it | — |

A suite is never silently skipped: it passes, fails, or is *reported*
unavailable. Pass extra arguments through after `--`:

```bash
./test/qtest run rest -- -k tenant        # pytest -k filter
./test/qtest run --docker backend         # force the containerized run
./test/qtest run --report out.json        # machine-readable outcomes
```

The classic entry points all still work and run exactly the same tests:
`make test` (backend, local venv), `make test-frontend` (vitest),
`make test-docker` (containerized), and `cd backend && pytest`.

**In CI** (`.github/workflows/ci.yml`): the backend job runs the whole pytest
suite against a throwaway PostgreSQL 16 in Docker, plus a migration-drift and
system-check pass; the frontend job type-checks (`tsc` covers
`test/frontend/` too), builds, and runs vitest.

**How the frontend tests talk to a server that isn't there.** Nothing in
`frontend/src` is mocked. `helpers/fakeApi.ts` installs a route table as the
axios *adapter* — the one seam axios provides for replacing the wire — on the
app's own `api` instance, so the real interceptors (bearer + workspace
headers, the single-flight 401 refresh, session teardown) run in every test.
Component tests render with React Testing Library under jsdom (each such file
declares `@vitest-environment jsdom`; pure-logic files stay in node) and a
fresh React Query client per test; the socket wrapper runs against a scripted
fake `WebSocket` under fake timers.

---

## The four focus areas

`qtest run` with no arguments runs these — one suite per subsystem the
application's correctness rests on:

| Suite | What it proves | Where |
|---|---|---|
| `rest` | The HTTP API behaves: every route the resolver serves demands auth unless explicitly classified public (a *discovery* sweep — adding an endpoint without classifying it fails); wire shapes match the DRF contract tests; `?limit=` is bounded; throttle scopes are configured; cross-tenant probes read as 404, never 403. | `backend/system/` (`test_api`, `test_contracts`, `test_rest_components`, `test_webstack`), `backend/identity/` |
| `react` | The frontend behaves: alert-cache merges never lose a socket-delivered alert to a stale refetch, reconnect backoff is capped and jittered, a missed heartbeat pong tears the socket down, parallel 401s refresh the token exactly once, a rejected refresh ends the session everywhere, the persisted session never contains the access token, each panel renders the API's shapes and drives its mutations, and `types.ts` still matches the golden fixtures. | `frontend/` |
| `celery-redis` | The evaluation fleet behaves: the sweep claims each due strategy exactly once (and rolls the claim back if the broker enqueue fails), the per-strategy eval lock outlives the task time limit, delivery reconciliation re-enqueues only what never recorded an outcome, retention prunes on schedule, and the broker speaks JSON only — never pickle. | `backend/system/` (`test_celery_redis`, `test_events`), `backend/strategies/`, `backend/watchlist/` |
| `postgres` | Storage behaves on the production engine: JSONB round-trips and containment queries, `CHECK` constraints and uniqueness enforced by the database itself, cascades vs `SET_NULL` on delete, a real two-connection `SELECT FOR UPDATE` block, the cursor-pagination index, and zero model↔migration drift. | `backend/system/test_postgres.py` |

Supporting suites: `indicators` (every formula from the `math/` chapters
pinned to hand-derived numbers), `journeys` (whole user sessions through the
API), and `contracts` (the frontend half of the dual pin).

Tests are matched to suites by **pytest markers**, applied automatically from
the directory (or, under `system/`, the file) a test lives in
(`test/backend/conftest.py`); the registry lives in `test/framework/suites.py`.
`pytest -m rest` works directly too.

---

## How the safeguards interlock

Three mechanisms make this suite self-policing rather than a checklist that
goes stale:

1. **The contract dual pin.** `backend/journeys/fixtures/*.json` is the single
   source of truth for wire shapes. `test_contract_fixtures.py` proves the
   *live API* produces exactly those shapes; `frontend/contract/contracts.test.ts`
   proves `types.ts` matches the *same files* — at compile time, via
   exhaustive key maps. Changing a serializer fails the backend pin → you
   update the fixture → the frontend stops compiling until `types.ts` moves in
   the same PR. The contract cannot drift on one side only.

2. **Discovery over enumeration.** The REST auth sweep walks the live URL
   resolver, and the beat-schedule test walks `CELERY_BEAT_SCHEDULE`; new
   routes and new periodic tasks are swept automatically, and a route the
   sweep can't classify is itself a failure.

3. **Production parity where it matters.** The database is the one external
   service tests use for real (PostgreSQL, same engine as production — so row
   locks, JSONB, and duration arithmetic are exercised, not mocked), while
   Celery runs eagerly, channels run in memory, and market data is synthetic —
   hermetic and deterministic everywhere determinism is what's under test.

---

## Audit regressions (`backend/strategies/test_known_bugs.py`)

The 2026-08 audit found real defects; each deterministic one was first pinned
as a non-strict `xfail` test encoding the **desired** behavior. The fixes have
since landed, the markers are gone, and the tests now guard the fixed behavior
permanently — filed with the feature they belong to (B1–B6 with the
strategies, B7 with the indicator math in `markets/test_indicators.py`):

| ID | Defect (fixed) |
|---|---|
| AUDIT-B1 | The circuit breaker tripped a strategy to FAILED without ever calling `notify_strategy_failed` — alerts stopped silently. |
| AUDIT-B2 | Delivery reconciliation used the strategy's *current* channel flags; it now works off the fire-time snapshot on the alert row. |
| AUDIT-B3 | Failure bookkeeping was a stale read-modify-write; it is now a conditional update that never reverts a concurrent user pause/re-arm. |
| AUDIT-B4 | PATCHing a flat field on a composite strategy returned 200 while silently discarding the change; it is now a 400 naming the field. |
| AUDIT-B5 | A redelivered task that found the eval lock held dropped the run (consuming the poll window); it now requeues once after the lock TTL. |
| AUDIT-B6 | With an AI node present, the graph compiler silently dropped conditions not wired into the tree; orphans are now a compile error. |
| AUDIT-B7 | The MACD histogram unmasked values before its own warm-up standard; the mask now covers `slow + signal − 1` bars. |

That is the pattern for future finds: pin the bug as xfail next to the code it
concerns, fix it, drop the marker in the fixing PR. The full audit (including
the frontend and security findings, all since patched) is in the description
of the PR that introduced these tests.

## Adding a test

1. Put it in the `test/backend/` directory of the **feature** it exercises
   (or `system/` when it spans features, `journeys/` for a whole session);
   the marker, and therefore its `qtest` suite, follows from the directory —
   or from the filename under `system/`. Frontend tests go under
   `test/frontend/` by module.
2. If it changes a wire shape, update the fixture and both pins in the same
   PR (the suite will force you to anyway — that's the point).
3. Pin behavior to **hand-derived values**, never to the code's own output —
   `test_indicators.py` is the house style.
4. New endpoint? The REST sweep will fail until you classify it (public or
   authenticated) in `test/backend/system/test_rest_components.py`.
