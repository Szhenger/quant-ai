# QuantAI — Network (everything that crosses a wire)

CS50 ends its networking story at "the browser sends an HTTP request and a server
responds." QuantAI is that story, plus everything that happens when the story has to keep
happening — five processes ([`runtime/`](../runtime/README.md)) on different machines,
staying consistent over nothing but sockets. This folder documents every protocol in play,
bottom-up, assuming only what CS50x taught: TCP/IP exists, HTTP is a text conversation,
and a port is a numbered door.

## The map — who talks to whom

```text
             HTTPS (REST/JSON)               SQL over TCP :5432
  browser ──────────────────────► api ◄──────────────────────► postgres
     │                            ▲ │                              ▲
     │        WSS (WebSocket)     │ │      RESP over TCP :6379     │
     └────────────────────────────┘ └──────────────────────► redis ◄── worker / beat
                                                (queue, channel layer, cache, locks)
```

Two kinds of traffic, two trust levels. The **browser ↔ api** edge crosses the public
internet, so it gets TLS, authentication, and origin checks. Everything to the right is
**backend-internal** — Postgres and Redis speak their own binary protocols with no
concept of "users", which is exactly why they must never face the internet (in dev,
compose publishes them on `127.0.0.1` *only*; in prod they live on a private network).

## Layer by layer: one API call

When the frontend calls `GET /api/v1/markets/AAPL/analysis/`, from the bottom up:

1. **DNS** — `quantai-api.onrender.com` becomes an IP address.
2. **TCP** — the browser opens a connection to port `443` (dev: `8000`).
3. **TLS** — the connection is encrypted before a single byte of HTTP flows. Behind
   Render's proxy the last hop is plain HTTP; Django trusts the proxy's
   `X-Forwarded-Proto` header (`SECURE_PROXY_SSL_HEADER` in settings) to know the client
   side was HTTPS.
4. **HTTP/1.1** — the request itself, carrying the two headers that [Chapter 9](../documentation/09-the-api-contract.md)
   is about: `Authorization: Bearer <JWT>` (who you are) and `X-Workspace-ID` (which
   tenant you're acting in).
5. **JSON** — the response body: the contract pinned by the golden fixtures in
   `backend/test/journeys/fixtures/`. Plus `ETag` (a revalidation fingerprint — a repeat
   request with `If-None-Match` costs a `304` instead of a recompute) and gzip
   (`Content-Encoding`), because indicator payloads are large, repetitive JSON.

## One origin in dev, two in prod (CORS)

An **origin** is scheme + host + port. Browsers enforce the *same-origin policy*: page
JavaScript can't freely read responses from a different origin unless that origin opts in
via **CORS** headers.

- **Development** — there's one origin, by trick: the Vite dev server (`:5173`) proxies
  `/api` and `/ws` to Daphne on `:8000` (see `frontend/vite.config.ts`). The browser only
  ever sees `localhost:5173`, so CORS never triggers.
- **Production** — the frontend is a static site on its own domain, so every API call is
  cross-origin. The backend allowlists exactly the frontend's origin
  (`CORS_ALLOWED_ORIGINS`), and — easy to miss — allowlists the custom `X-Workspace-ID`
  **header** too: the browser's *preflight* (`OPTIONS`) asks permission per header, and an
  unlisted custom header fails every request from a cross-origin page.

## The WebSocket: a phone line, not a mailbox

HTTP is request→response→done; alerts need the server to speak **first**. A WebSocket
starts life as a normal HTTP request with `Upgrade: websocket` — then the connection stays
open as a two-way pipe.

The connect URL is `wss://…/ws/alerts/<workspace_id>/?token=<JWT>`, and each piece is a
deliberate decision (`backend/config/asgi.py` reads top-to-bottom in this order):

1. **Origin check first** (`OriginValidator`) — browsers on foreign origins are refused
   before any token is examined. Defence in depth on top of token auth.
2. **`?token=` in the query string** — a browser cannot set an `Authorization` header on
   a WebSocket, so the JWT rides the URL (`engine/ws_auth.py` resolves it, and re-checks
   `is_active`, mirroring the HTTP path).
3. **Workspace ownership** — the consumer verifies the workspace in the URL is really
   yours before joining its channel group. Same two checkpoints as HTTP: identity, then
   tenancy.

The raw protocol can't detect a *half-open* line (a slept laptop, a dead proxy), so the
client adds an application-level **heartbeat** (ping/pong every 25s) and reconnects with
capped exponential backoff **plus jitter** — a thousand clients that lost the same server
must not all redial in the same second (`frontend/src/realtime/`).

## The distributed part: how a worker reaches your browser

The evaluation that fires an alert runs in the **worker** process — which holds no
WebSockets. The API process holds your socket — but didn't run the evaluation. The bridge
is the **channel layer** (Django Channels backed by Redis pub/sub):

```text
worker: group_send("workspace_<id>", alert) ──► redis ──► api: every consumer in
                                                          that group pushes the
                                                          frame down its socket
```

The worker publishes to a *named group*; Redis fans it out to whichever api process(es)
hold sockets subscribed to that group. Neither side knows the other's address — that
indirection is what lets you run three workers and two api instances without any of them
caring. The same Redis also carries the Celery **job queue** (beat → worker) and the
**eval locks** that make alerts exactly-once ([Chapter 10](../documentation/10-concurrency-and-safety.md)).

## Ports, in one table

| Port | Protocol | Who listens | Exposed to |
|---|---|---|---|
| 5173 | HTTP (Vite dev server + proxy) | frontend, dev only | your browser |
| 8000 | HTTP + WebSocket (Daphne/ASGI) | api | browser (dev); Render proxy (prod) |
| 5432 | Postgres wire protocol | db | backend processes only (loopback in dev) |
| 6379 | RESP (Redis) | redis | backend processes only (loopback in dev) |
| 443 | HTTPS/WSS (TLS termination) | Render's proxy, prod only | the internet |

## The health check is a network statement

`GET /healthz/` doesn't just return `200` — it queries the database and round-trips the
shared cache *from inside the app*, so "healthy" means "**my** connections to Postgres
and Redis work", not "the process exists". Compose gates service startup on it, and
Render won't route production traffic to a deploy until it answers. One URL, and the
whole topology above has to be standing for it to say yes.
