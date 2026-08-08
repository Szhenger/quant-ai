# QuantAI — Architecture

QuantAI turns the workflow of a quantitative researcher into a product: follow
markets, define numeric conditions on them, and get AI-contextualised alerts when
those conditions fire. This document describes how the pieces fit together and why.

## Components

| Layer | Tech | Responsibility |
|---|---|---|
| SPA | React + TypeScript + Vite | Strategy builders (form + node graph), market analysis, live alerts |
| API gateway | Django 5 + DRF | Auth (JWT), workspaces, watchlist, strategy CRUD, market analysis |
| Real-time | Django Channels (Redis layer) | Push alerts to the browser over an authenticated WebSocket |
| Scheduler | Celery Beat | Enqueue due strategies every 60 s |
| Worker | Celery | Evaluate a strategy: prices → indicator → condition → AI → alert |
| Market data | `marketdata` package | Pluggable providers (yfinance + synthetic) + numpy indicators |
| AI | `ai` package | Anthropic Claude signal-vs-noise assessment (degrades gracefully) |

## Data model

- **Workspace** (`core`) — the tenant boundary. A user owns one or more workspaces.
- **WatchedTicker** (`core`) — a followed market (drives the analysis dashboard).
- **Strategy** (`strategies`) — a user-defined rule: ticker, indicator + params,
  operator, threshold, optional AI directive, delivery channels, poll interval, and
  cooldown. Tracks `last_evaluated_at`, `last_triggered_at`, `last_metric_value`.
- **Alert** (`strategies`) — one record per firing: the metric value, the AI rationale,
  the human-readable message, and per-channel delivery status.

## Multi-tenant isolation

There is no ambient "current workspace". Every workspace-scoped request must send an
`X-Workspace-ID` header; `core.workspaces.resolve_active_workspace` validates that the
workspace exists **and** is owned by the authenticated user before any query runs.
Workspace CRUD is additionally filtered by `owner`. WebSocket connections carry the
JWT as a `?token=` query parameter (browsers can't set WS headers); the consumer
verifies workspace ownership on connect and closes with code 4003 otherwise.

## Quantitative indicators (`marketdata/indicators.py`)

Each indicator is a pure numpy function producing a full series aligned to the price
closes (with `None` during warm-up), so evaluation can read both the latest value and
the previous value — the latter powers `cross_above` / `cross_below` operators.

Implemented: `Z_SCORE`, `RSI` (Wilder smoothing), `SMA_CROSS` (fast−slow spread),
`MACD_HIST`, `PCT_CHANGE`, `VOLATILITY` (annualised), `PRICE`. Unknown indicators
raise rather than silently returning a default, so a misconfigured strategy fails
loudly instead of firing spuriously.

## Market-data providers (`marketdata/providers.py`)

A small `BaseProvider` interface with two implementations:

- **YFinanceProvider** — real Yahoo Finance data, no API key.
- **SyntheticProvider** — a deterministic seeded random walk keyed on the ticker, used
  offline and in tests so the whole pipeline runs anywhere.

`get_provider()` selects via `MARKETDATA_PROVIDER` (`auto` | `yfinance` | `synthetic`)
and wraps the primary in a `ResilientProvider` that falls back to synthetic data on any
transient error — a data-source hiccup degrades output, it never crashes evaluation.

## AI contextualisation (`ai/claude_client.py`)

When a strategy's quantitative condition fires and `ai_enabled` is set, `ClaudeClient.assess`
sends the ticker, the metric, the user's directive, and recent headlines to Claude
(`claude-opus-4-8` by default) using structured outputs, and returns
`{trigger, rationale, confidence}`. With no `ANTHROPIC_API_KEY` (or the SDK absent, or an
API error) it degrades gracefully: the alert fires on the quantitative condition alone
and says so in the rationale.

## The evaluation loop (`strategies/tasks.py`)

- `sweep_due_strategies` (Celery Beat, every 60 s) finds active strategies whose
  `poll_interval_minutes` has elapsed and enqueues `evaluate_strategy` for each.
- `evaluate_strategy`:
  1. pulls `lookback_days(indicator)` of prices from the provider;
  2. computes the indicator (value + previous);
  3. checks the operator/threshold; on failure records `last_evaluated_at` and stops;
  4. honours the cooldown so a persistent condition doesn't spam;
  5. asks Claude to confirm the signal (or straight-through if AI is disabled);
  6. creates an `Alert` and delivers it, then stamps `last_triggered_at`.
  Any exception is caught, recorded on `last_error`, and returned — one bad strategy
  never takes down the sweep.

## Alert delivery (`strategies/delivery.py`)

Three channels, each opted into per strategy and each recording its own status on
`Alert.delivery`:

- **In-app / WebSocket** — `channel_layer.group_send` to `ws_<workspace_id>`, streamed
  to every connected client for that workspace by `AlertConsumer`.
- **Email** — Django `send_mail` to the workspace owner (console backend in DEBUG).
- **Webhook** — a `POST` of the alert JSON to the strategy's `webhook_url`.

## Why the C++ kernel / RSS pipeline is gone

The project began life as an RSS-feed reader ("SimpleFeed++") with an unused AVX-512
C++ kernel, a sentence-transformer triage pipeline, and education/planning verticals.
None of it served the quant-research goal, and much of it didn't run. It was removed;
quant math is done in numpy (fast enough, trivially testable, no FFI to build) and the
real-time layer now delivers **alerts** rather than feed items.
