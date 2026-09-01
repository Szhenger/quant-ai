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

```text
src/
├── api/
│   ├── client.ts        # the axios instance: JWT + X-Workspace-ID interceptors, single-flight 401 refresh
│   ├── hooks.ts         # every server read/write as a typed React Query hook (keys namespaced by workspace)
│   ├── types.ts         # TypeScript shapes of the API payloads (Strategy, Alert, MarketAnalysis, …)
│   └── errors.ts        # extractError(): turn an axios error into a human string
├── store/
│   └── auth.ts          # Zustand store: access/refresh tokens, active workspace, login/register/logout (persisted)
├── realtime/
│   ├── socket.ts        # a WebSocket that stays up: reconnect w/ backoff+jitter, heartbeat ping/pong
│   ├── backoff.ts       # the reconnect pacing math (pure, unit-tested)
│   ├── merge.ts         # cache-merge helpers: dedup on socket prepend, optimistic read-state (pure, unit-tested)
│   └── useAlertsSocket.ts # app-level wiring: one socket per session, alerts land in the query cache
├── components/
│   ├── MarketsPanel.tsx        # search a ticker → price series + every indicator; manage the watchlist
│   ├── StrategiesPanel.tsx     # list strategies, evaluate one on demand, host the two builders
│   ├── StrategyForm.tsx        # the flat form → POST /strategies/ (fields driven by GET /indicators/)
│   ├── StrategyGraphBuilder.tsx# the React-Flow visual builder → POST /strategies/deploy-graph/ (lazy-loaded chunk)
│   ├── AlertsPanel.tsx         # alert history: infinite cursor pages, mark-read/mark-all-read, the "Live" dot
│   ├── ReplayPanel.tsx         # signal replay: window/cooldown controls around the replay endpoint
│   ├── ReplayChart.tsx         # the replay timeline: price path + a marker at every would-have-fired bar
│   └── LineChart.tsx           # dependency-free responsive SVG price chart
├── pages/
│   └── LoginPage.tsx    # register / log in
├── App.tsx              # the shell: sidebar tabs + live unread badge, workspace switcher, the session socket
├── queryClient.ts       # the React Query client: dedup, abort-on-unmount, background revalidation
├── main.tsx             # Vite entry point
└── styles.css
```

The three panels map one-to-one onto the sidebar tabs in `App.tsx`. Server state lives in
the React Query cache behind `api/hooks.ts`: concurrent consumers share one request, cached
data paints instantly while revalidating, and every query key is prefixed with the workspace
id — so switching workspace switches cache *namespaces* and can never bleed one tenant's rows
into another's view. Switching also remounts the panels (keyed on `workspaceId`) to reset
their local UI state, and the session socket reconnects to the new workspace's channel.

## How it maps to the backend (Chapter 9)

Two files carry almost all the contract logic; read them alongside
[Chapter 9](../documentation/09-the-api-contract.md) and it clicks.

- **`store/auth.ts`** — the login desk. `register` and `login` call the bare auth endpoints
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
npm test           # vitest: pure realtime logic + journey sequences + wire-contract pins
```

The vitest files live with the rest of the suite at the repo root, in
[`test/frontend/`](../test/README.md); `npm test` (and `tsc`) reach out to them from here.

Two of those test files are part of the cross-stack **UX-invariant framework**:

- `test/frontend/api/contracts.test.ts` pins `types.ts` against the golden wire fixtures in
  `test/backend/journeys/fixtures/` — the same files the backend's
  `test_contract_fixtures.py` pins its serializers against. Each type has a
  compile-time-exhaustive key map, so adding/removing a field anywhere forces the
  fixture, the serializer test, `types.ts`, and the key map to move in one PR.
- `test/frontend/realtime/journeys.test.ts` pins the *sequences* the live UI produces over the
  alert cache (socket bursts racing refetches, triage flows, redelivery after
  mark-read) — the interleavings that lose data when the cache logic gets "simplified".

The build splits deliberately: app code (~35 kB) + long-cacheable vendor chunks, with the
React-Flow graph builder in its own **lazy** chunk that never downloads unless someone opens
the graph tab.

---

New here? The app is only half the story — read the [course](../README.md) to learn *why* every
number on these panels exists. Chapters 8–10 are the backend this cockpit is flying.
