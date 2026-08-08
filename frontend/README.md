# QuantAI — Frontend (the cockpit)

This is the human's window onto the engine. Everything the [backend](../backend/README.md)
computes — markets, strategies, and live alerts from Chapters 8–10 — is put in front of you
here: a React + TypeScript single-page app, built with Vite. It talks to the backend through
the exact contract of [Chapter 9](../math/09-the-api-contract.md), and it holds a live
WebSocket open so alerts arrive the moment they fire.

Best part for a learner: it runs against the **offline synthetic backend**, so you can click
around the whole thing with **no API key and no internet**. The same z-scores you derive by
hand in the docs are the ones lighting up on screen.

## What's in `src/`

```text
src/
├── api/
│   ├── client.ts        # the axios instance: JWT + X-Workspace-ID interceptors, single-flight 401 refresh
│   ├── types.ts         # TypeScript shapes of the API payloads (Strategy, Alert, MarketAnalysis, …)
│   └── errors.ts        # extractError(): turn an axios error into a human string
├── store/
│   └── auth.ts          # Zustand store: access/refresh tokens, active workspace, login/register/logout (persisted)
├── components/
│   ├── MarketsPanel.tsx        # search a ticker → price series + every indicator; manage the watchlist
│   ├── StrategiesPanel.tsx     # list strategies, evaluate one on demand, host the two builders
│   ├── StrategyForm.tsx        # the flat form → POST /strategies/ (fields driven by GET /indicators/)
│   ├── StrategyGraphBuilder.tsx# the React-Flow visual builder → POST /strategies/deploy-graph/
│   ├── AlertsPanel.tsx         # alert history + the live WebSocket (the "Live" dot)
│   └── LineChart.tsx           # dependency-free responsive SVG price chart
├── pages/
│   └── LoginPage.tsx    # register / log in
├── App.tsx              # the shell: sidebar tabs (Markets / Strategies / Alerts), workspace switcher
├── main.tsx             # Vite entry point
└── styles.css
```

The three panels map one-to-one onto the sidebar tabs in `App.tsx`. Switching workspace
remounts the active panel (it's keyed on `workspaceId`), which forces a fresh fetch **and**
reconnects the WebSocket to the new workspace's channel.

## How it maps to the backend (Chapter 9)

Two files carry almost all the contract logic; read them alongside
[Chapter 9](../math/09-the-api-contract.md) and it clicks.

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

## The live-alert WebSocket (Chapter 9)

`AlertsPanel.tsx` first fetches history with `GET /alerts/`, then opens the persistent pipe:

```ts
const wsBase = window.location.origin.replace("http", "ws");
const url = `${wsBase}/ws/alerts/${workspaceId}/?token=${access}`;
const socket = new WebSocket(url);
```

Note the access token in the **query string** — a browser can't set headers on a WebSocket,
so the JWT rides in the URL exactly as [Chapter 9](../math/09-the-api-contract.md) describes.
Incoming `{"type": "alert", ...}` frames are prepended to the list (de-duplicated by id), and
the little **Live / Offline** dot reflects the socket's open state. This is the server speaking
first — no polling.

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

Start the [backend](../backend/README.md) first (or `docker compose up` from the repo root),
then `npm run dev`. Because the default backend serves the **synthetic** market, you can
register a throwaway account and explore the whole cockpit with no keys and no network.

Production build:

```bash
npm run build      # tsc type-check, then a static Vite bundle in dist/
```

---

New here? The app is only half the story — read the [course](../README.md) to learn *why* every
number on these panels exists. Chapters 8–10 are the backend this cockpit is flying.
