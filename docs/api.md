# QuantAI — API Reference

Base path: `/api/v1`. All requests/responses are JSON. Interactive schema at `/api/docs/`.

## Auth
- `POST /auth/register/` — `{username, email, password}` → 201 (also creates a default workspace).
- `POST /auth/token/` — `{username, password}` → `{access, refresh}`.
- `POST /auth/token/refresh/` — `{refresh}` → `{access}`.

Send `Authorization: Bearer <access>` on every other endpoint. Workspace-scoped
endpoints also require `X-Workspace-ID: <workspace uuid>`.

## Workspaces & watchlist
- `GET/POST /workspaces/` — owner-scoped; workspace `{id, name, created_at}`. (No `X-Workspace-ID` needed.)
- `GET/POST/DELETE /watchlist/` — `{id, ticker, note, created_at}` in the active workspace.

## Market analysis
- `GET /indicators/` → `{indicators:[{key,label,unit,defaults,help}], operators:[{key,label}]}`.
- `GET /markets/{ticker}/analysis/?days=180` →
  `{ticker, provider, dates:[...], closes:[...], latest_price, indicators:{KEY:{label,unit,value,params}}}`.

## Strategies
- `GET /strategies/` — paginated list (active workspace).
- `POST /strategies/` — create. Body:
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
- `PATCH /strategies/{id}/`, `DELETE /strategies/{id}/`.
- `POST /strategies/deploy-graph/` — compile a React-Flow graph. Body:
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
- `POST /strategies/{id}/evaluate/` — evaluate now (manual/testing) →
  `{status: "alerted"|"quant_not_met"|"cooldown"|"ai_suppressed"|"error", ...}`.

## Alerts
- `GET /alerts/?unread=1` — paginated `{id, strategy_name, ticker, indicator, operator,
  threshold, metric_value, ai_used, ai_rationale, message, delivery, is_read, created_at}`.
- `POST /alerts/{id}/mark-read/`.

## WebSocket (live alerts)
- Connect: `ws://<host>/ws/alerts/{workspace_id}/?token=<access>`.
- Server sends `{"type": "connected", ...}` then `{"type": "alert", "alert": {...}}` per fired alert.
- Closes 4001 (unauthenticated) or 4003 (workspace not owned by the user).
