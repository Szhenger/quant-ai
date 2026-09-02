# Chapter 9 — The API as a contract

> **The question.** Three very different things want to talk to QuantAI: a human clicking around in a browser, a Python script you wrote on a plane, and the server itself trying to push you an alert at 3am. They were written by different people, at different times, in different languages. How do they agree on *anything* — and how does the server know it's really you, and only shows you *your* data? That agreement is an **API**, and this chapter is about reading it as what it really is: a contract.

---

## 9.1 An API is a promise, not a program

Forget the acronym for a second. Suppose you and I agree, in writing, on exactly one sentence:

> "If you send me a `POST` to `/api/v1/auth/token/` with a username and password in the body, I will send you back an access token — or a `401` if you're wrong."

That sentence is a **contract**. Neither of us needs to know how the other is implemented. You could rewrite your client in Rust tomorrow; as long as you keep sending that request, my server keeps its half of the deal. I could swap Postgres for something else next year; as long as I keep returning that token, your script never notices. An **API** (Application Programming Interface) is nothing more than the full set of those promised request/response sentences — a treaty between programs written by strangers, or, just as often, between you-now and you-in-six-months who has forgotten everything.

QuantAI speaks a particular dialect of this treaty called **REST**. Two ideas carry it:

- **Resources.** The nouns of the system get addresses. A workspace, a strategy, an alert, a watchlist entry — each is a *thing* you can point at with a URL: `/api/v1/strategies/`, `/api/v1/alerts/`.
- **Verbs.** You act on those nouns with the standard HTTP methods: `GET` (read it), `POST` (create one), `PATCH` (change part of one), `DELETE` (remove it).

So `GET /api/v1/strategies/` means "read my strategies," and `POST /api/v1/strategies/` means "create a new one." The verb says what, the URL says which. That's the whole grammar.

> **Short: why REST and not "just call the function"?** Because the caller and the callee live in different processes, often on different machines, written in different languages. You cannot pass a Python object to a browser. But *everyone* can agree on "an HTTP request with some JSON in it." REST is popular precisely because it commits to the smallest thing every program already knows how to do — send text over HTTP — and builds meaning on top of it. It is the lowest common denominator, chosen on purpose.

This is the last chapter of the engineering arc. [Chapter 8](08-from-math-to-system.md) turned a formula into a service that runs forever; this chapter is the *door* to that service — how the outside world reaches in safely. [Chapter 10](10-concurrency-and-safety.md) is what happens deep inside when two things reach in at once.

## 9.2 Two different questions: *who are you?* and *what may you do?*

Every request to a shared server has to survive two checkpoints, and beginners routinely blur them:

- **Authentication** — *who are you?* Proving identity. This is the login desk.
- **Authorization** — *what are you allowed to touch?* Proving permission. This is the velvet rope in front of each room.

They are genuinely separate. A logged-in user (authenticated) still must not read *another* user's alerts (that would be an authorization failure). QuantAI answers the first question with a **token** (§9.3) and the second with a **workspace check** (§9.4). Keep the two ideas in different pockets; we'll need both.

## 9.3 Stateless identity: the JWT

Here is the naive way to remember who's logged in: when you sign in, the server writes "session `abc123` = user Shuo" into a table, hands you a cookie that says `abc123`, and looks you up in that table on every request. This works, and for one server it's fine. But notice what it costs: **every server that handles your requests must be able to read that shared session table.** Add a second server, a worker, a WebSocket process, and now they all need a common memory of who's who. That shared memory is a bottleneck and a single point of failure.

QuantAI takes the other road: a **stateless JWT** (JSON Web Token). The trick is beautiful. Instead of the server *remembering* who you are, the token itself *carries* the claim "I am user 42," and that claim is **cryptographically signed** by the server's secret key. When a request arrives, any server can check the signature with the same key and know — without looking anything up — that the token is genuine and hasn't been tampered with. Identity travels *with the request*. No shared session table. The API server, the Celery worker, and the WebSocket consumer can all verify you independently.

> **Short: signed, not secret.** A JWT is *not encrypted*. Anyone can base64-decode it and read the claims inside (`user_id: 42`). What they cannot do is *forge* one, because they don't have the signing key — change a single character and the signature no longer matches. So the rule is: never put a secret *in* a JWT, but absolutely trust that the `user_id` in a valid one is real. It's a sealed envelope with a window, not a locked box.

### The access/refresh split

If a token proves identity and needs no server lookup, one leaks — copied from a log, a browser extension, a shoulder — and the thief *is* you until it expires. Statelessness giveth (no lookup) and taketh away (you can't easily un-issue what you never stored). QuantAI's answer is to hand you **two** tokens, from `backend/config/settings.py`:

```python
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}
```

- The **access token** is the one you actually send on every request. It is short-lived — **60 minutes**. That short life is the whole point: it *limits the blast radius of a leak*. A stolen access token is a bomb with a one-hour fuse.
- The **refresh token** lives much longer — **7 days** — but you use it for exactly one thing: asking for a fresh access token when the old one expires (`POST /auth/token/refresh/`). It never rides along on ordinary requests, so it's exposed far less often.

And `ROTATE_REFRESH_TOKENS` with `BLACKLIST_AFTER_ROTATION` means each time you refresh, the old refresh token is retired and blacklisted — so even a captured refresh token has a shelf life. The design trades a little inconvenience (tokens expire; you refresh) for a large safety margin (a leak self-heals in an hour).

> **Short: where's the "log out" if it's stateless?** This is the honest tension. True statelessness has no revoke button — the server isn't tracking your tokens, so it can't tear one up. The refresh-token *blacklist* is the pragmatic compromise: the long-lived credential is trackable and revocable, while the short-lived one is left stateless and simply allowed to expire. Most real systems live at exactly this compromise.

You send the access token on every protected request as a header:

```
Authorization: Bearer <access-token>
```

That's the DRF setting `AUTH_HEADER_TYPES: ("Bearer",)` in action, and `JWTAuthentication` as the default authentication class turns that header back into `request.user`.

## 9.4 Multi-tenancy over HTTP: the `X-Workspace-ID` header

Now the *second* checkpoint — authorization. [Chapter 8](08-from-math-to-system.md) introduced the **workspace** as the unit of isolation: your strategies, your watchlist, your alerts all belong to a workspace, and one user may own several. Authentication told the server *who* you are. But most requests also need to know *which workspace* you're acting in — and, critically, the server must refuse if you point at a workspace that isn't yours.

QuantAI carries the active workspace in a custom header on every workspace-scoped request:

```
X-Workspace-ID: <workspace uuid>
```

And here is the enforcement, the single choke point every scoped request flows through, in `backend/identity/workspaces.py`:

```python
WORKSPACE_HEADER = "HTTP_X_WORKSPACE_ID"


def resolve_active_workspace(request) -> Workspace:
    workspace_id = request.META.get(WORKSPACE_HEADER)
    if not workspace_id:
        raise PermissionDenied("Missing X-Workspace-ID header.")
    try:
        return Workspace.objects.get(id=workspace_id, owner=request.user)
    except (Workspace.DoesNotExist, ValidationError, ValueError):
        raise NotFound("Workspace not found or not owned by the current user.")
```

Read that query slowly, because it *is* the isolation from Chapter 8, enforced at the door:

```python
Workspace.objects.get(id=workspace_id, owner=request.user)
```

It doesn't just look up the workspace by id — it demands `owner=request.user` **in the same query**. Ask for a workspace that exists but belongs to someone else and the lookup finds nothing, so you get a `404 NotFound`, indistinguishable from asking for one that doesn't exist at all. That's deliberate: the server won't even *confirm* that another tenant's workspace exists. Notice too that the two checkpoints combine — `request.user` came from the JWT (authentication), and `owner=request.user` is the permission test (authorization). Identity and permission meet in one line.

> **Short: why a header and not the URL?** You *could* put the workspace id in every path (`/api/v1/workspaces/<id>/strategies/`). Carrying it in a header instead keeps the resource URLs clean and makes "the workspace I'm currently in" a single ambient piece of context the frontend sets once (we'll see it do exactly that in the client interceptor, §9.7). Both are defensible; QuantAI chose the header. Either way, the *check* is what matters — a header you don't validate is worse than useless.

## 9.5 The endpoint reference, taught

Here is the full contract. It's worth having the table in front of you, but a table only tells you the *shape* of each promise — this section tells you the *why*. (The living, clickable version is the OpenAPI schema the server generates itself, at `/api/docs/`.)

Everything hangs off base path `/api/v1`, wired up in `backend/config/urls.py`:

```python
urlpatterns = [
    # Authentication (stateless JWT)
    path("api/v1/auth/register/", RegisterView.as_view(), name="register"),
    path("api/v1/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/v1/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # Workspaces + watchlist
    path("api/v1/", include("core.urls")),

    # Strategies, alerts, market analysis
    path("api/v1/", include("strategies.urls")),
]
```

### The table

| Area | Method & path | What it promises | Why it exists |
|---|---|---|---|
| **Auth** | `POST /auth/register/` | `{username, email, password}` → `201`; also creates a default workspace | You can't do anything without an identity; registration mints one *and* the first tenant to act in, so a fresh user is immediately usable |
| | `POST /auth/token/` | `{username, password}` → `{access, refresh}` | The login desk (§9.3): trade credentials for the two tokens |
| | `POST /auth/token/refresh/` | `{refresh}` → `{access}` | Renew a 60-minute access token without re-typing your password — the mechanism that makes short access lifetimes bearable |
| **Workspaces** | `GET/POST /workspaces/` | owner-scoped list/create; `{id, name, created_at}` | The tenant boundary itself. *No `X-Workspace-ID` needed* — you're choosing *which* workspace, so you can't already be in one |
| **Watchlist** | `GET/POST/PATCH/DELETE /watchlist/` | `{id, ticker, note, refresh_interval_hours, recompute_interval_hours, refreshed_at, recomputed_at, has_page, created_at}` in the active workspace; plus `/watchlist/{id}/page/`, `/refresh/`, `/history/` for the compiled stock page | The set of tickers you care about — scoped to the workspace in the header |
| **Indicators** | `GET /indicators/` | `{indicators:[{key,label,unit,defaults,default_threshold,help,summary,readings}], operators:[{key,label}]}` | A self-describing catalog. The UI builds its strategy form from this, so adding an indicator server-side makes it appear in the client with no frontend change |
| **Market** | `GET /markets/{ticker}/analysis/?days=180` | `{ticker, provider, dates, closes, latest_price, indicators:{KEY:{label,unit,value,params}}}` | Everything Chapters 1–6 computed, for one ticker, in one call: the price series plus every indicator's current value |
| **Strategies** | `GET /strategies/` | paginated list (active workspace) | Your monitoring rules |
| | `POST /strategies/` | create from an explicit body (see below) | Define a rule: ticker + indicator + operator + threshold + AI + delivery + timing |
| | `PATCH /strategies/{id}/`, `DELETE /strategies/{id}/` | update / remove | Ordinary edit and teardown of one rule |
| | `POST /strategies/deploy-graph/` | compile a React-Flow node graph into a strategy | The visual builder (§9.6): the UI sends nodes and edges, the server compiles them into the same `Strategy` |
| | `POST /strategies/{id}/evaluate/` | evaluate now → `{status: "alerted"｜"quant_not_met"｜"cooldown"｜"ai_suppressed"｜"locked"｜"error", ...}`; with a real worker fleet the call returns `202 {status: "queued"}` and the outcome lands on the strategy row / alerts | Run the rule *right now*, for testing — the manual trigger behind the scheduled sweep of Chapters 8 & 10 |
| **Alerts** | `GET /alerts/?unread=1` | paginated alert list | Read your history; `unread=1` filters to what you haven't seen |
| | `POST /alerts/{id}/mark-read/` | mark one read | Clear the "NEW" badge — a tiny bit of read/unread state |

A representative `POST /strategies/` body — this *is* the encoded form of "AAPL 20-day z-score below −2, and ask the AI before you bother me":

```json
{
  "name": "AAPL oversold", "ticker": "AAPL",
  "indicator": "Z_SCORE", "params": {"window": 20},
  "operator": "<", "threshold": -2.0,
  "ai_enabled": true, "ai_prompt": "Is the earnings thesis broken?",
  "notify_in_app": true, "notify_email": false, "webhook_url": "",
  "poll_interval_minutes": 15, "cooldown_minutes": 60
}
```

Two fields worth pausing on, because they're the seam to the next chapter: `poll_interval_minutes` (how often the scheduler considers this rule) and `cooldown_minutes` (how long after firing it must stay quiet). Those two numbers are the entire subject of [Chapter 10](10-concurrency-and-safety.md) — the difference between "alert me when this is true" and "alert me *once* when this becomes true."

> **Short: lists come paginated.** `GET /strategies/` uses limit/offset pagination (page size 50): `{count, next, previous, results: [...]}`. `GET /alerts/` — the one table that grows without bound — uses **cursor** pagination instead: `{next, previous, results: [...]}` with *no* `count`, because every cursor page is a constant-cost range scan (page 100 of an offset scan costs 100× page 1, and concurrently-arriving alerts can't shift a cursor window the way they shift an offset). Your code reads `results` either way.

> **Webhook deliveries are at-least-once.** A delivery whose response is lost after your receiver processed it will be retried, and the reconciliation sweep can re-send after a crash. Every delivery carries `X-QuantAI-Alert-Id` — dedupe on it. Verify `X-QuantAI-Signature` (HMAC-SHA256 of `"<X-QuantAI-Timestamp>.<body>"` with your strategy's `webhook_secret`) and reject stale timestamps.

## 9.6 Two ways to build the same strategy

Notice the API offers *two* create paths: `POST /strategies/` takes a flat JSON body, while `POST /strategies/deploy-graph/` takes a graph of nodes and edges:

```json
{
  "name": "AAPL oversold",
  "nodes": [
    {"id": "n1", "type": "asset", "data": {"ticker": "AAPL"}},
    {"id": "n2", "type": "quant", "data": {"indicator": "Z_SCORE", "operator": "<", "value": -2.0}},
    {"id": "n3", "type": "ai", "data": {"prompt": "Is the thesis broken?"}}
  ],
  "edges": [{"source": "n1", "target": "n2"}, {"source": "n2", "target": "n3"}]
}
```

Why two doors to the same room? Because they serve two humans. The flat form is what a *script* wants — terse, direct. The graph is what the *visual builder* in the frontend produces: an `asset → quant → ai` pipeline the user wired together by dragging boxes. The server *compiles* that graph down to exactly the same `Strategy` the flat form would have made. Same contract, two ergonomics. That's a recurring API design move: meet each caller where it is, converge on one internal representation.

## 9.7 WebSockets: when the server needs to speak first

Everything so far shares one deep assumption: **the client asks, the server answers.** HTTP is strictly request/response — the server cannot say anything until spoken to. That's perfect for "show me my strategies." It is hopeless for an **alert**.

Think about what an alert *is*. A z-score crosses −2 at 2:47pm while your laptop is closed. The event is **server-initiated** — the server knows something you don't, and it needs to *push* it to you. With plain HTTP your only option is to *poll*: ask "anything new?" every few seconds, forever, mostly hearing "no." Wasteful, and always a few seconds late.

So QuantAI opens a second kind of connection: a **WebSocket**. Where HTTP is a series of postcards (one question, one answer, connection closed), a WebSocket is a **phone line left off the hook** — a single, persistent, bidirectional pipe that stays open so *either* side can speak the moment it has something to say. The client opens it once; the server pushes alerts down it for as long as you're connected. This is the delivery half of Chapter 8's system finally reaching the user.

### The authentication twist

But WebSockets break our tidy §9.3 story, and the reason is almost silly: **a browser won't let JavaScript set custom headers when opening a WebSocket.** No headers means no `Authorization: Bearer ...`. Our whole identity scheme rode in a header. Now what?

The tempting workaround is a `?token=` query parameter — but a URL is the one part of a
request that everything on the path writes down: proxy and load-balancer access logs, APM
traces, browser history. A bearer token must never live where logging is the default.

There is exactly one header a browser *will* let you influence on a WebSocket:
`Sec-WebSocket-Protocol`, the subprotocol negotiation list. So the client offers two
"protocols" — the real one, and the token dressed as one:

```
ws://<host>/ws/alerts/{workspace_id}/
Sec-WebSocket-Protocol: quantai.v1, quantai.token.<access-token>
```

(A JWT is unpadded base64url plus dots — all legal subprotocol characters.) A small
middleware plucks the token out before the connection is accepted, in
`backend/strategies/ws_auth.py`, and the consumer completes the handshake by selecting
`quantai.v1` — a server must echo one of the *offered* subprotocols or the browser drops
the connection, which is why the token rides as a second, never-selected entry:

```python
class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        token = None
        for offered in scope.get("subprotocols") or []:
            if offered.startswith(TOKEN_SUBPROTOCOL_PREFIX):
                token = offered[len(TOKEN_SUBPROTOCOL_PREFIX):]
                break
        scope["user"] = await self._authenticate(token)
        return await super().__call__(scope, receive, send)

    @database_sync_to_async
    def _authenticate(self, token):
        if not token:
            return AnonymousUser()
        try:
            from rest_framework_simplejwt.tokens import AccessToken
            access = AccessToken(token)
            return get_user_model().objects.get(id=access["user_id"], is_active=True)
        except Exception:  # noqa: BLE001
            return AnonymousUser()
```

Same JWT, same signature check (`AccessToken(token)` validates it) — just arriving by a different door because the front door was locked. If anything is wrong, the user becomes `AnonymousUser` and the consumer will reject them.

> **Short: why the access token and not the refresh token?** Because the socket only needs to prove *who* you are for the life of the connection, and the access token is the least-powerful credential that can do that: it lives only 60 minutes (§9.3) and cannot mint new tokens. Even riding in a header, a credential on a long-lived connection deserves the smallest blast radius available. Defense in depth: no single decision is load-bearing.

### The ownership check, again

Authentication got us a user on the connection. Now the *same* authorization question from §9.4 returns — is this workspace actually yours? — enforced in `AlertConsumer.connect()`, in `backend/strategies/consumers.py`:

```python
async def connect(self):
    user = self.scope.get("user")
    self.workspace_id = self.scope["url_route"]["kwargs"]["workspace_id"]

    if user is None or not user.is_authenticated:
        await self.close(code=4001)  # unauthenticated
        return
    if not await self._owns(user, self.workspace_id):
        await self.close(code=4003)  # not your workspace
        return

    self.group = f"ws_{self.workspace_id}"
    await self.channel_layer.group_add(self.group, self.channel_name)
    await self.accept()
    await self.send_json({"type": "connected", "workspace_id": self.workspace_id})
```

Two custom close codes make the two failures legible:

- **`4001`** — no valid token; we don't know who you are (authentication failed).
- **`4003`** — we know who you are, but this isn't your workspace (authorization failed).

That is §9.2 in miniature, one more time, at a different door. And `_owns` is the WebSocket twin of `resolve_active_workspace` — the identical ownership query, guarding the identical isolation:

```python
@database_sync_to_async
def _owns(self, user, workspace_id):
    from django.core.exceptions import ValidationError
    try:
        return Workspace.objects.filter(id=workspace_id, owner=user).exists()
    except (ValidationError, ValueError):
        return False
```

Once accepted, the connection joins a per-workspace group named `ws_<workspace_id>`. When a strategy fires (Chapter 10), the worker does a group-send to exactly that group, and the consumer relays it to the browser:

```python
async def alert_message(self, event):
    await self.send_json({"type": "alert", "alert": event["data"]})
```

The client sees `{"type": "connected", ...}` the instant it joins, then `{"type": "alert", "alert": {...}}` for each alert, live. The group name *is* the isolation boundary: an alert for your workspace is sent to `ws_<yours>`, and a connection that survived the `4003` check is the only kind that's ever joined to that group. Tenancy, enforced at the door, then trusted downstream.

## 9.8 Worked walkthrough: one full request lifecycle

Let's trace a single user from "nobody" to "receiving a live alert," touching every layer this chapter built. Imagine a script (or `curl`) on the left, the server on the right.

**1. Register.** No token yet — this is the one place you have no identity.

```
POST /api/v1/auth/register/
{"username": "shuo", "email": "shuo@example.com", "password": "s3cret!"}
→ 201 Created        (and a default workspace is created for you)
```

**2. Get tokens.** Trade the password for the pair.

```
POST /api/v1/auth/token/
{"username": "shuo", "password": "s3cret!"}
→ 200 {"access": "eyJhbGciOi...", "refresh": "eyJhbGciOi..."}
```

**3. Find your workspace.** This call needs the access token, but *not* a workspace header — you're choosing among workspaces, not acting inside one.

```
GET /api/v1/workspaces/
Authorization: Bearer eyJhbGciOi...
→ 200 {"count": 1, "results": [{"id": "7f3a…-uuid", "name": "Default", ...}]}
```

**4. Create a strategy.** Now both checkpoints fire: the `Authorization` header proves *who*, the `X-Workspace-ID` header says *where*, and `resolve_active_workspace` confirms you own it before anything is written.

```
POST /api/v1/strategies/
Authorization: Bearer eyJhbGciOi...
X-Workspace-ID: 7f3a…-uuid
{"name": "AAPL oversold", "ticker": "AAPL", "indicator": "Z_SCORE",
 "params": {"window": 20}, "operator": "<", "threshold": -2.0,
 "ai_enabled": false, "poll_interval_minutes": 15, "cooldown_minutes": 60}
→ 201 {"id": "...", "name": "AAPL oversold", ...}
```

**5. Open the WebSocket.** The token rides in the one header a browser allows — the subprotocol list (§9.7). The middleware authenticates it; the consumer checks ownership and either closes `4001/4003` or accepts.

```
WS  ws://localhost:8000/ws/alerts/7f3a…-uuid/
    Sec-WebSocket-Protocol: quantai.v1, quantai.token.eyJhbGciOi...
← {"type": "connected", "workspace_id": "7f3a…-uuid"}
```

**6. Receive an alert.** Minutes later the scheduler evaluates your rule (Chapters 8 & 10); the z-score is −2.3; it fires. The worker group-sends to `ws_7f3a…`, and down your open pipe comes:

```
← {"type": "alert", "alert": {"id": "...", "ticker": "AAPL",
     "indicator": "Z_SCORE", "metric_value": -2.3, "message": "AAPL Z_SCORE < -2.0 …",
     "is_read": false, "created_at": "2026-08-08T14:47:02Z"}}
```

No polling. The server spoke first, because by now it could — you'd left the line open. Every idea in this chapter appears exactly once in that trace: contract, authentication, authorization, the two headers, the two-token split, and the second protocol.

## 9.9 In the code

The map, so you can read the real thing:

- **Routes** — `backend/config/urls.py` (the base-path table above) includes one `urls.py` per feature app: `identity` (`workspaces`, `limits/`), `watchlist` (`watchlist` and its `page/`, `refresh/`, `history/` actions), `markets` (`indicators/`, `markets/<ticker>/analysis/`) and `strategies` (`strategies`, `alerts`).
- **Authorization choke point** — `resolve_active_workspace` in `backend/identity/workspaces.py`. Every scoped view calls it; it is the single line where tenancy is enforced over HTTP.
- **WebSocket auth** — `JWTAuthMiddleware` in `backend/strategies/ws_auth.py` (token from the `Sec-WebSocket-Protocol` subprotocol list, never the URL), and the `4001/4003` ownership check in `AlertConsumer.connect()` in `backend/strategies/consumers.py`. The socket is routed in `backend/strategies/routing.py` and mounted in `backend/config/asgi.py`, where HTTP and WebSocket protocols split.
- **Token policy** — the `SIMPLE_JWT` block in `backend/config/settings.py` (lifetimes, rotation, blacklist).

## 9.10 Worked example: read the contract like a lawyer

Take the single line

```python
return Workspace.objects.get(id=workspace_id, owner=request.user)
```

and answer, from the code alone: what response does a caller get in each case?

1. **Header missing entirely.** `resolve_active_workspace` never reaches the query — it raises `PermissionDenied` first → **403**.
2. **Header present, valid UUID, your workspace.** The `get` succeeds → the view proceeds → **2xx**.
3. **Header present, valid UUID, but someone *else's* workspace.** `owner=request.user` fails to match → `DoesNotExist` → **404 NotFound**.
4. **Header present but garbage (`"banana"`).** Not a UUID → `ValidationError`/`ValueError`, caught → **404 NotFound**.

Cases 3 and 4 return the *same* `404`. That's not laziness — it's the point. The server refuses to leak the difference between "exists but not yours" and "doesn't exist," so a curious attacker learns nothing by probing UUIDs.

## 9.11 Problem set

1. **Why not put the JWT in the URL?** The obvious WebSocket workaround is a `?token=` query parameter (§9.7 rejects it). List three concrete ways a token in a URL leaks that a token in a request header does not. Then explain how the `Sec-WebSocket-Protocol` scheme avoids all three while still working from a browser — and why the server must echo `quantai.v1` (not the token entry) when it accepts. What would go wrong if someone lazily put the *refresh* token in the subprotocol slot instead of the access token?

2. **The tenancy check.** Rewrite `resolve_active_workspace` as the naive two-step it must *not* be: first `Workspace.objects.get(id=workspace_id)`, then a separate `if workspace.owner != request.user`. Both "work." Explain what an attacker can learn from the *timing* or *error message* of the two-step version that the single-query version hides. Why is "authorization folded into the lookup" a security property, not just tidier code?

3. **Two doors, one room (§9.6).** You add a fourth node type to the visual builder. Which endpoint's compiler must learn about it, and does `POST /strategies/` change at all? Use this to argue why converging both create-paths onto one internal `Strategy` was worth it.

4. **Stateless has no logout.** A user's laptop is stolen with a valid access token in memory. Given §9.3, how long is the worst-case exposure, and which of the two tokens can you actually revoke? Sketch what you'd add to make access tokens revocable too, and state honestly what you'd give up (hint: you'd be walking back toward §9.3's session table).

5. **`4001` vs `4003`.** A user reports "my alerts panel says Offline." Using the consumer's two close codes, write the two-question diagnostic you'd run and what each answer implies about *which* checkpoint failed. Why is it a genuine kindness to the client that these are two different codes and not one generic "connection refused"?

6. **Poll vs. push.** Estimate the requests per day if the alerts panel *polled* `GET /alerts/?unread=1` every 3 seconds instead of holding a WebSocket, for a user who is online 8 hours. Now estimate the WebSocket's cost when *zero* alerts fire. Which idle cost is lower, and by how much? (This is the number that justifies the whole second protocol.)

---

Next: the rule fired. But *when*, exactly, and how do we guarantee it fires **once** and not three times when a worker, a scheduler, and a manual `evaluate` all glance at it in the same minute? That "exactly once" is where real money and real bugs live — [Chapter 10 — Concurrency & safety](10-concurrency-and-safety.md).
