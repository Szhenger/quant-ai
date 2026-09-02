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
  // n / m: per-ticker refresh (qualitative) and recompute (quantitative) cadences.
  refresh_interval_hours: number;
  recompute_interval_hours: number;
  refreshed_at: string | null;
  recomputed_at: string | null;
  has_page: boolean;
  created_at: string;
}

// One plain-language band on a field's own scale: `{op, at, text}` is a
// comparison in the strategy operator vocabulary (crosses excluded); a band
// with no `op` is the catch-all and comes last.
export interface IndicatorReading {
  op?: "<" | ">" | "<=" | ">=";
  at?: number;
  text: string;
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
  // Field-registry metadata (see markets/indicators.py): whether this field
  // leads a stock-page summary, and how to word a value.
  summary: boolean;
  readings: IndicatorReading[];
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

// --- Stock page (watchlist MVP): the two measures, detailed + summarised ------

export interface NewsItem {
  title: string;
  source: string;
  published_at: string | number | null;
}

export interface WeekView {
  dates: string[];
  closes: number[];
  start: string | null;
  end: string | null;
  change_pct: number | null;
}

export interface QuantMeasure {
  key: string;
  label: string;
  unit: string;
  value: number | null;
  reading: string;
}

export interface QuantitativeSummary {
  latest_price: number | null;
  week_change_pct: number | null;
  headline: string;
  measures: QuantMeasure[];
}

export interface QuantitativeDetailed extends MarketAnalysis {
  week: WeekView;
}

export interface QualitativeDetailed {
  window_days: number;
  news: NewsItem[];
  summary: string;
  summary_source: "claude" | "fallback";
  synthetic: boolean;
}

export interface QualitativeSummary {
  headline: string;
  article_count: number;
  summary_source: "claude" | "fallback";
}

export interface StockPage {
  ticker: string;
  quantitative: QuantitativeDetailed;
  quantitative_summary: QuantitativeSummary;
  qualitative: QualitativeDetailed;
  qualitative_summary: QualitativeSummary;
  data_synthetic: boolean;
  refreshed_at: string | null;
  recomputed_at: string | null;
  refresh_interval_hours: number;
  recompute_interval_hours: number;
  // True while a recompile of either measure is in flight: the server keeps
  // serving the last compiled page meanwhile, and the client polls until the
  // fresh one lands.
  refreshing: boolean;
}

export interface QuantSnapshotEntry {
  taken_at: string;
  recomputed_at: string | null;
  summary: QuantitativeSummary | null;
}

export interface StockHistory {
  ticker: string;
  snapshots: QuantSnapshotEntry[];
}

export type StrategyStatus = string;

// Upper bounds on what one strategy costs the fleet per day (identity/limits.py):
// one evaluation per poll interval; with AI on, at most one paid call per
// cooldown window and never more than one per evaluation.
export interface CostEstimate {
  evaluations_per_day: number;
  ai_calls_per_day_max: number;
}

// GET /limits/: the account guards this workspace runs under, and how much of
// each is used. `strategies_remaining` is null when the cap is unlimited.
export interface Limits {
  strategy_cap: number;
  strategy_count: number;
  strategies_remaining: number | null;
  ai_daily_budget: number;
  ai_calls_today: number;
  ai_calls_remaining: number;
  ai_budget_resets_at: string;
}

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
  // Read-only: evaluations/day and the ceiling on paid AI calls/day.
  cost_estimate: CostEstimate;
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

// The delivery + scheduling knobs every strategy carries, as sent on the wire.
// Shared by the plain form, the inline editor and the graph builder.
export type StrategyDelivery = Pick<
  Strategy,
  "poll_interval_minutes" | "cooldown_minutes" | "notify_in_app" | "notify_email" | "webhook_url"
>;

// POST /strategies/deploy-graph/: the React Flow graph plus the same delivery
// settings the plain form sends; the server compiles the graph into a tree.
export interface GraphDeployRequest extends StrategyDelivery {
  name: string;
  nodes: { id: string; type: string | undefined; data: unknown }[];
  edges: { source: string; target: string }[];
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

// Workspace event frames pushed over the socket (see backend/common/events.py):
// "something about X changed" — identifiers only, the client refetches.
export type WorkspaceEvent =
  | { event: "stockpage.updated"; watch_id: string; ticker: string; measure: string }
  | { event: "strategy.evaluated"; strategy_id: string; status: string; value?: number | null }
  | { event: string; [key: string]: unknown };

export interface AuthTokens {
  access: string;
  refresh: string;
}
