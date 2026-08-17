export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// Alerts use cursor (keyset) pagination: constant cost per page, no count.
export interface CursorPage<T> {
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface UnreadCount {
  unread: number;
}

export interface Workspace {
  id: string;
  name: string;
  created_at: string;
}

export interface WatchedTicker {
  id: string;
  ticker: string;
  note: string;
  created_at: string;
}

export interface Indicator {
  key: string;
  label: string;
  unit: string;
  defaults: Record<string, unknown>;
  // Sensible starting threshold on this indicator's own scale; null for
  // price-scaled indicators where no universal default exists.
  default_threshold: number | null;
  help: string;
}

export interface Operator {
  key: string;
  label: string;
}

export interface IndicatorCatalog {
  indicators: Indicator[];
  operators: Operator[];
}

export interface MarketIndicatorValue {
  label: string;
  unit: string;
  value: number | null;
  params: Record<string, unknown>;
}

export interface MarketAnalysis {
  ticker: string;
  provider: string;
  synthetic: boolean;
  dates: string[];
  closes: number[];
  latest_price: number;
  indicators: Record<string, MarketIndicatorValue | null>;
}

export type StrategyStatus = string;

export interface Strategy {
  id: string;
  name: string;
  ticker: string;
  indicator: string;
  params: Record<string, unknown>;
  operator: string;
  threshold: number;
  // Composite mode: an AND/OR condition tree. Authoritative when present; the
  // flat fields above are then a representative leaf for display.
  condition: unknown | null;
  // Read-only: the strategy's real firing rule as one human-readable line,
  // correct for both simple and composite strategies.
  condition_summary: string;
  ai_enabled: boolean;
  ai_prompt: string;
  notify_in_app: boolean;
  notify_email: boolean;
  webhook_url: string;
  // Read-only, auto-generated: HMAC key receivers use to verify the
  // X-QuantAI-Signature header on webhook deliveries.
  // Present on create/detail/rotate responses; omitted from LIST responses
  // (the signing secret has no business in every page load).
  webhook_secret?: string;
  status: StrategyStatus;
  poll_interval_minutes: number;
  cooldown_minutes: number;
  // Circuit breaker: consecutive failed evaluations; the backend pauses the
  // strategy to status "failed" at its threshold.
  consecutive_failures: number;
  last_evaluated_at: string | null;
  last_triggered_at: string | null;
  last_metric_value: number | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface EvaluateResult {
  // "queued": the evaluation was dispatched to the worker fleet (202) — the
  // outcome lands on the strategy row / alerts, not in this response.
  // "locked": another evaluation of the same strategy is already running.
  status:
    | "alerted"
    | "quant_not_met"
    | "cooldown"
    | "ai_suppressed"
    | "error"
    | "queued"
    | "locked"
    | string;
  [key: string]: unknown;
}

export interface ReplayFire {
  index: number;
  date: string | null;
  metric: number | null;
}

export interface ReplayResult {
  strategy_id: string;
  ticker: string;
  condition: string;
  provider: string;
  synthetic: boolean;
  cooldown_bars: number;
  bars: number;
  fire_count: number;
  fires: ReplayFire[];
  dates: string[];
  closes: number[];
}

export interface Alert {
  id: string;
  strategy: string | null;
  strategy_name: string | null;
  ticker: string;
  indicator: string;
  operator: string;
  threshold: number;
  metric_value: number | null;
  ai_used: boolean;
  ai_rationale: string | null;
  // AI verdict's self-reported confidence (0..1); null when AI didn't run.
  ai_confidence: number | null;
  message: string;
  // The evaluated condition tree that fired this alert (reproducible audit row).
  condition_detail: unknown;
  // True when this alert was computed from synthetic fallback data, not real market data.
  data_synthetic: boolean;
  delivery: Record<string, unknown> | string | null;
  is_read: boolean;
  created_at: string;
}

export interface AuthTokens {
  access: string;
  refresh: string;
}
