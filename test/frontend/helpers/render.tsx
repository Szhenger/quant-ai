/**
 * Render helpers: a fresh React Query client per test (no retries, no
 * background refetch noise), a signed-in session in the auth store, and the
 * fixture shapes the panels render.
 */
import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { useAuthStore } from "../../../frontend/src/session/auth";
import { useRealtimeStore } from "../../../frontend/src/realtime/store";
import type { Alert, IndicatorCatalog, Limits, Strategy } from "../../../frontend/src/contract/types";

export const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";

export function signIn(overrides: Partial<ReturnType<typeof useAuthStore.getState>> = {}) {
  useAuthStore.setState({
    access: "access-token",
    refresh: "refresh-token",
    workspaceId: WORKSPACE_ID,
    username: "trader",
    workspaces: [{ id: WORKSPACE_ID, name: "Desk", created_at: "2026-01-01T00:00:00Z" }],
    ...overrides,
  });
}

export function signOut() {
  useAuthStore.setState({
    access: null, refresh: null, workspaceId: null, username: null, workspaces: [],
  });
  useRealtimeStore.setState({ status: "down", strategyNotice: null, evaluations: {} });
}

export function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false, staleTime: 0, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  const utils = render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  return { ...utils, client };
}

// --- fixtures -----------------------------------------------------------------

export const catalog: IndicatorCatalog = {
  indicators: [
    {
      key: "RSI", label: "RSI", unit: "", defaults: { period: 14 }, default_threshold: 30,
      help: "Relative Strength Index", summary: true,
      readings: [
        { op: "<", at: 30, text: "oversold" },
        { op: ">", at: 70, text: "overbought" },
        { text: "neutral" },
      ],
    },
    {
      key: "PRICE", label: "Price", unit: "$", defaults: {}, default_threshold: null,
      help: "The latest close", summary: false, readings: [],
    },
  ],
  operators: [
    { key: "<", label: "<" },
    { key: ">", label: ">" },
  ],
};

export const limits: Limits = {
  strategy_cap: 50, strategy_count: 1, strategies_remaining: 49,
  ai_daily_budget: 200, ai_calls_today: 3, ai_calls_remaining: 197,
  ai_budget_resets_at: "2026-09-03T00:00:00Z",
};

export function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: "s1", name: "AAPL oversold", ticker: "AAPL",
    indicator: "RSI", params: { period: 14 }, operator: "<", threshold: 30,
    condition: null, condition_summary: "RSI < 30",
    cost_estimate: { evaluations_per_day: 96, ai_calls_per_day_max: 1 },
    ai_enabled: true, ai_prompt: "",
    notify_in_app: true, notify_email: false, webhook_url: "",
    status: "active", poll_interval_minutes: 15, cooldown_minutes: 1440,
    consecutive_failures: 0,
    last_evaluated_at: null, last_triggered_at: null, last_metric_value: null, last_error: null,
    created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

export function alert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: "a1", strategy: "s1", strategy_name: "AAPL oversold", ticker: "AAPL",
    indicator: "RSI", operator: "<", threshold: 30, metric_value: 27.5,
    ai_used: true, ai_rationale: "Momentum washed out on heavy volume.", ai_confidence: 0.8,
    message: "AAPL: RSI < 30 (value 27.5000). Momentum washed out.",
    condition_detail: {}, data_synthetic: false,
    delivery: { in_app: { ok: true } }, is_read: false,
    created_at: "2026-09-02T12:00:00Z",
    ...overrides,
  };
}
