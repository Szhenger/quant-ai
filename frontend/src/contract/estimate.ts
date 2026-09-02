import type { CostEstimate } from "./types";

const MINUTES_PER_DAY = 24 * 60;

/**
 * Mirror of engine.limits.estimate_strategy_cost, so the builders can show
 * the cost of a strategy as the user types, before anything is deployed.
 * The server recomputes it on save and echoes it as `cost_estimate`; the two
 * are pinned to the same numbers in tests.
 *
 * Returns null while the inputs aren't valid whole minutes yet.
 */
export function estimateStrategyCost(
  pollIntervalMinutes: number,
  cooldownMinutes: number,
  aiEnabled: boolean,
): CostEstimate | null {
  if (!Number.isInteger(pollIntervalMinutes) || pollIntervalMinutes < 1) return null;
  if (!Number.isInteger(cooldownMinutes) || cooldownMinutes < 1) return null;
  const evaluations = Math.ceil(MINUTES_PER_DAY / pollIntervalMinutes);
  const aiCalls = aiEnabled
    ? Math.min(evaluations, Math.ceil(MINUTES_PER_DAY / cooldownMinutes))
    : 0;
  return { evaluations_per_day: evaluations, ai_calls_per_day_max: aiCalls };
}
