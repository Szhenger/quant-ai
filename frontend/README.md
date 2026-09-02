# QuantAI — Frontend (the cockpit)

This is the human's window onto the engine. Everything the [backend](../backend/README.md)
computes — markets, strategies, and live alerts from Chapters 8–10 — is put in front of you
here: a React + TypeScript single-page app, built with Vite. It talks to the backend through
the exact contract of [Chapter 9](../documentation/09-the-api-contract.md), and it holds a live
WebSocket open so alerts arrive the moment they fire.

Best part for a learner: it runs against the **offline synthetic backend**, so you can click
around the whole thing with **no API key and no internet**. The same z-scores you derive by
hand in the docs are the ones lighting up on screen.

## What's in `src/`

The tree is organized by **feature**, not by kind of file: the three sidebar tabs are the
three folders under `features/`, each owning its screens *and* its server-state hooks. What
sits outside `features/` is the small set of things every feature shares.

```text
src/
├── main.tsx             # Vite entry point
├── config.ts            # API_BASE / WS_BASE — where the backend lives (env-driven for split origins)
├── app/
│   ├── App.tsx          # the shell: sidebar tabs + live unread badge, workspace switcher, the session socket
│   ├── queryClient.ts   # the React Query client: dedup, abort-on-unmount, background revalidation
│   └── styles.css       # one stylesheet, grouped by the feature that owns each rule
├── session/
│   ├── auth.ts          # Zustand store: tokens, active workspace, login/register/logout (persisted); useWorkspaceId()
│   └── LoginPage.tsx    # register / log in
├── api/
│   ├── client.ts        # the axios instance: JWT + X-Workspace-ID interceptors, single-flight 401 refresh
│   ├── keys.ts          # the React Query key registry (feature hooks own queries; realtime invalidates by key)
│   ├── catalog.ts       # useIndicatorCatalog(): the field registry from GET /indicators/, shared by two features
│   └── errors.ts        # extractError(): turn an axios error into a human string
├── contract/            # the frontend half of the wire contract — pure modules, pinned by test/frontend/contract/
│   ├── types.ts         # TypeScript shapes of the API payloads (Strategy, Alert, StockPage, …)
│   ├── readings.ts      # readIndicator(): word a value from the field registry's reading bands (mirrors the backend)
│   ├── estimate.ts      # estimateStrategyCost(): the deploy-time cost estimate (mirrors identity/limits.py)
│   └── cursor.ts        # relativizeCursor(): keep DRF's absolute cursor links same-origin
├── realtime/
│   ├── socket.ts        # a WebSocket that stays up: reconnect w/ backoff+jitter, heartbeat ping/pong
│   ├── backoff.ts       # the reconnect pacing math (pure, unit-tested)
│   ├── merge.ts         # cache-merge helpers: dedup on socket prepend, optimistic read-state (pure, unit-tested)
│   ├── store.ts         # Zustand: socket status, strategy notices, worker evaluation outcomes
│   └── useAlertsSocket.ts # app-level wiring: one socket per session; alerts land in the query cache, events invalidate it
└── features/
    ├── markets/
    │   ├── hooks.ts            # analysis, watchlist, stock page + history queries and mutations
    │   ├── MarketsPanel.tsx    # search a ticker → price series + every indicator; manage the watchlist
    │   ├── StockDetail.tsx     # a watched ticker's compiled page: two measures, cadences, continuity trail
    │   └── LineChart.tsx       # dependency-free responsive SVG price chart
    ├── strategies/
    │   ├── hooks.ts            # strategies list, replay, evaluate, limits, create/deploy/update/delete/rotate
    │   ├── StrategiesPanel.tsx # list strategies, evaluate one on demand, host the two builders
    │   ├── StrategyForm.tsx    # the flat form → POST /strategies/ (fields driven by the catalog)
    │   ├── StrategyGraphBuilder.tsx # the React-Flow visual builder → POST /strategies/deploy-graph/ (lazy chunk)
    │   ├── StrategyEditor.tsx  # inline editor for an existing strategy (+ webhook secret rotation)
    │   ├── DeliverySettings.tsx# the delivery/scheduling knobs shared by all three builders
    │   ├── CostEstimate.tsx    # "what will this cost?" shown before deploy; useAtStrategyCap()
    │   ├── ReplayPanel.tsx     # signal replay: window/cooldown controls around the replay endpoint
    │   └── ReplayChart.tsx     # the replay timeline: price path + a marker at every would-have-fired bar
    └── alerts/
        ├── hooks.ts            # infinite cursor pages, unread count, optimistic mark-read / mark-all-read
        ├── AlertsPanel.tsx     # alert history, the "Live" dot, triage actions
        └── AlertDetail.tsx     # one alert's audit tree + per-channel delivery outcomes
```

The three feature folders map one-to-one onto the sidebar tabs in `app/App.tsx`. Server state
lives in the React Query cache behind each feature's `hooks.ts`: concurrent consumers share one
request, cached data paints instantly while revalidating, and every query key (registered once
in `api/keys.ts`) is prefixed with the workspace id — so switching workspace switches cache
*namespaces* and can never bleed one tenant's rows into another's view. Switching also remounts
the panels (keyed on `workspaceId`) to reset their local UI state, and the session socket
reconnects to the new workspace's channel.

Dependencies run one way: `features/` → `api/`, `contract/`, `realtime/`, `session/`; `realtime/`
→ `api/keys`, `session/`; `session/` → `api/client`. The transport never imports the session
store — it reads tokens through a small bridge the store binds at load (`bindSession`), which is
what keeps `api/` and `session/` free of an import cycle.

## How it maps to the backend (Chapter 9)

Two files carry almost all the contract logic; read them alongside
[Chapter 9](../documentation/09-the-api-contract.md) and it clicks.

- **`session/auth.ts`** — the login desk. `register` and `login` call the bare auth endpoints
  (`/auth/register/`, `/auth/token/`) with a plain axios call — no token exists yet, so they
  can't go through the authenticated client. On success it stashes `{access, refresh, username,
  workspaceId}` and **persists** them (Zustand's `persist`), so a page refresh keeps you logged
  in. It also loads your workspaces and picks an active one.

- **`api/client.ts`** — every *other* request flows through this one axios instance, which does
  the two Chapter 9 jobs automatically:
  - a **request interceptor** attaches `Authorization: Bearer <access>` and, when a workspace is
    active, the `X-Workspace-ID` header — so you never hand-wire auth into a component;
  - a **response interceptor** does **single-flight 401 refresh**: when the access token expires
    mid-session, the first `401` triggers one call to `/auth/token/refresh/`, and any *other*
    requests that 401 at the same moment await that same promise instead of each hammering the
    endpoint. If refresh succeeds the original request is retried transparently; if it fails the
    session is cleared and the app falls back to the login page.

That interceptor is the client half of the two-checkpoint story in Chapter 9: identity
(`Authorization`) and tenancy (`X-Workspace-ID`), set once, applied everywhere.

## The live-alert WebSocket (Chapters 9 & 10)

One socket per session, owned by the app shell (`realtime/useAlertsSocket.ts`), not by any
panel — so alerts arrive and the sidebar's unread badge ticks up whichever tab you're on.
The access token rides in the **subprotocol list** (`Sec-WebSocket-Protocol` is the one header
a browser lets a WebSocket set, and unlike a `?token=` query string it never lands in proxy
access logs or browser history), exactly as [Chapter 9](../documentation/09-the-api-contract.md)
describes. The URL and the offered subprotocols are rebuilt at every (re)connect, so a
refreshed token is picked up without tearing the socket down.

The raw browser WebSocket reports clean closes but not *half-open* connections — a dead
proxy or a slept laptop leaves a socket that looks open and delivers nothing. Alerts are the
product here, so `realtime/socket.ts` adds what the primitive lacks:

- an application-level **heartbeat**: ping every 25s; a missed pong within 10s declares the
  connection dead and tears it down;
- **reconnection with capped exponential backoff + full jitter** (`backoff.ts`), so a fleet
  of clients that lost the same server don't stampede it in lockstep the moment it returns;
- incoming alerts land in the **React Query cache** (`merge.ts`), de-duplicated by id against
  every cached page — the same alert arriving over the socket *and* in a racing background
  refetch renders exactly once. That's the client-side half of Chapter 10.

The same socket is also the app's **subscription channel**. Background work on the server
(a stock page recompiling, a strategy evaluation finishing on a worker) publishes a small
`{type: "event", event: "stockpage.updated" | "strategy.evaluated", ...ids}` frame to the
workspace group (`backend/common/events.py`), and `useAlertsSocket.ts` invalidates the matching
React Query key so the panel refetches through the normal authenticated REST path. Events carry
identifiers, never data. The old timers (a 30s strategies poll, a 2.5s stock-page poll) still
exist in each feature's `hooks.ts` but only run while the socket is down — see `useSocketLive()` in
`realtime/store.ts` — so a broken connection degrades to polling rather than to a frozen screen.

The **Live / Connecting / Offline** dot in the Alerts panel reflects the socket's true state.

## Run it

Needs **Node 20+**.

```bash
npm install
npm run dev        # Vite dev server at http://localhost:5173
```

The dev server proxies to the backend on `:8000`, configured in `vite.config.ts`, so there's
no CORS dance in development:

```ts
proxy: {
  "/api": { target: "http://localhost:8000", changeOrigin: true },  // REST
  "/ws":  { target: "ws://localhost:8000",   ws: true },            // WebSocket
}
```

Start the [backend](../backend/README.md) first (or `docker compose -f runtime/docker-compose.yml up` from the repo root),
then `npm run dev`. Because the default backend serves the **synthetic** market, you can
register a throwaway account and explore the whole cockpit with no keys and no network.

Production build and tests:

```bash
npm run build      # tsc type-check, then a static Vite bundle in dist/
npm test           # vitest: pure logic, wire-contract pins, and every panel rendered against a fake wire
```

The vitest files live with the rest of the suite at the repo root, in
[`test/frontend/`](../test/README.md); `npm test` (and `tsc`) reach out to them from here.

Three layers, all under `test/frontend/`:

- **Pure modules** (`realtime/`, `contract/`): backoff, cache merges, cursor math, readings,
  the cost estimate — table-driven, no DOM.
- **The transport and the session** (`session/`): `api/client.ts` and `session/auth.ts` run
  against a fake wire installed at the axios adapter boundary, so the real interceptors are
  under test — parallel 401s refresh exactly once, a rejected refresh ends the session
  everywhere, a transient refresh failure fails only its request, and the persisted session
  never contains the access token. The socket wrapper (`realtime/socket.test.ts`) runs against
  a scripted `WebSocket` with fake timers: heartbeat, missed-pong teardown, backoff.
- **Rendered components** (`features/`, `app/`, the login page): each panel renders under
  jsdom with React Testing Library against the same fake wire, and its mutations are asserted
  on the wire — mark-read is optimistic, delete needs two clicks, a queued evaluation resolves
  when the worker's event lands in the realtime store, a restored session renders before the
  workspace does.

Two of those files are part of the cross-stack **UX-invariant framework**:

- `test/frontend/contract/contracts.test.ts` pins `contract/types.ts` against the golden wire fixtures in
  `test/backend/journeys/fixtures/` — the same files the backend's
  `test_contract_fixtures.py` pins its serializers against. Each type has a
  compile-time-exhaustive key map, so adding/removing a field anywhere forces the
  fixture, the serializer test, `contract/types.ts`, and the key map to move in one PR.
- `test/frontend/realtime/journeys.test.ts` pins the *sequences* the live UI produces over the
  alert cache (socket bursts racing refetches, triage flows, redelivery after
  mark-read) — the interleavings that lose data when the cache logic gets "simplified".

The build splits deliberately: app code (~35 kB) + long-cacheable vendor chunks, with the
React-Flow graph builder in its own **lazy** chunk that never downloads unless someone opens
the graph tab.

---

New here? The app is only half the story — read the [course](../README.md) to learn *why* every
number on these panels exists. Chapters 8–10 are the backend this cockpit is flying.
