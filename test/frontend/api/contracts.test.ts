/**
 * Golden-fixture contract pins — the frontend half of the dual pin.
 *
 * `test/backend/journeys/fixtures/*.json` is the single source of truth for
 * the wire shapes. The backend's `test_contract_fixtures.py` proves the live
 * API produces exactly those shapes; THIS file proves `types.ts` matches the
 * very same files — at compile time via the exhaustive `contractKeys` maps
 * (add or remove a field on a type and the map below stops compiling), and at
 * runtime by comparing the fixture's actual keys.
 *
 * The loop: a serializer change fails the backend pin → the fixture gets
 * updated → this file fails (compile or runtime) until types.ts and the key
 * map are updated in the same PR. The contract can never drift on one side.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type {
  Alert,
  AuthTokens,
  CostEstimate,
  MarketAnalysis,
  MarketIndicatorValue,
  ReplayFire,
  ReplayResult,
  Strategy,
} from "../../../frontend/src/api/types";

const FIXTURE_DIR = new URL("../../backend/journeys/fixtures/", import.meta.url);

function load(name: string): Record<string, unknown> {
  const path = fileURLToPath(new URL(`${name}.json`, FIXTURE_DIR));
  return JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
}

/** Compile-time exhaustive key list: the literal argument must name every key
 * of T (mapped type) and nothing else (excess property check). */
function contractKeys<T>(keys: { [K in keyof Required<T>]: true }): string[] {
  return Object.keys(keys).sort();
}

const sortedKeys = (o: Record<string, unknown>) => Object.keys(o).sort();

describe("wire-contract fixtures match types.ts", () => {
  it("Strategy (and its cost estimate)", () => {
    const fixture = load("strategy");
    expect(sortedKeys(fixture.cost_estimate as Record<string, unknown>)).toEqual(
      contractKeys<CostEstimate>({ evaluations_per_day: true, ai_calls_per_day_max: true }),
    );
    expect(sortedKeys(fixture)).toEqual(
      contractKeys<Strategy>({
        id: true, name: true, ticker: true, indicator: true, params: true,
        operator: true, threshold: true, condition: true,
        condition_summary: true, cost_estimate: true, ai_enabled: true,
        ai_prompt: true, notify_in_app: true, notify_email: true,
        webhook_url: true, webhook_secret: true, status: true,
        poll_interval_minutes: true, cooldown_minutes: true,
        consecutive_failures: true, last_evaluated_at: true,
        last_triggered_at: true, last_metric_value: true, last_error: true,
        created_at: true, updated_at: true,
      }),
    );
  });

  it("Alert", () => {
    expect(sortedKeys(load("alert"))).toEqual(
      contractKeys<Alert>({
        id: true, strategy: true, strategy_name: true, ticker: true,
        indicator: true, operator: true, threshold: true, metric_value: true,
        ai_used: true, ai_rationale: true, ai_confidence: true, message: true,
        condition_detail: true, data_synthetic: true, delivery: true,
        is_read: true, created_at: true,
      }),
    );
  });

  it("MarketAnalysis (and every indicator entry)", () => {
    const fixture = load("market_analysis");
    expect(sortedKeys(fixture)).toEqual(
      contractKeys<MarketAnalysis>({
        ticker: true, provider: true, synthetic: true, dates: true,
        closes: true, latest_price: true, indicators: true,
      }),
    );
    const indicatorKeys = contractKeys<MarketIndicatorValue>({
      label: true, unit: true, value: true, params: true,
    });
    const indicators = fixture.indicators as Record<string, Record<string, unknown>>;
    expect(Object.keys(indicators).length).toBeGreaterThan(0);
    for (const entry of Object.values(indicators)) {
      expect(sortedKeys(entry)).toEqual(indicatorKeys);
    }
  });

  it("ReplayResult (and its fires)", () => {
    const fixture = load("replay");
    expect(sortedKeys(fixture)).toEqual(
      contractKeys<ReplayResult>({
        strategy_id: true, ticker: true, condition: true, provider: true,
        synthetic: true, cooldown_bars: true, bars: true, fire_count: true,
        fires: true, dates: true, closes: true,
      }),
    );
    const [fire] = fixture.fires as Record<string, unknown>[];
    expect(sortedKeys(fire!)).toEqual(
      contractKeys<ReplayFire>({ index: true, date: true, metric: true }),
    );
  });

  it("AuthTokens", () => {
    expect(sortedKeys(load("auth_tokens"))).toEqual(
      contractKeys<AuthTokens>({ access: true, refresh: true }),
    );
  });
});

describe("UX honesty invariants hold in the canonical alert", () => {
  const alert = load("alert") as unknown as Alert;

  it("synthetic data is disclosed in flag AND message", () => {
    expect(alert.data_synthetic).toBe(true);
    expect(alert.message.startsWith("[SYNTHETIC DATA]")).toBe(true);
  });

  it("no fabricated confidence when the AI layer did not run", () => {
    expect(alert.ai_used).toBe(false);
    expect(alert.ai_confidence).toBeNull();
  });
});
