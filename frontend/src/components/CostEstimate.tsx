import { useLimits } from "../api/hooks";
import { estimateStrategyCost } from "../api/estimate";
import type { DeliverySettings } from "./DeliverySettings";

/**
 * "What will this strategy cost?", shown before deploy: evaluations per day,
 * the ceiling on paid AI calls per day as a share of the user's daily budget,
 * and how many strategy slots the workspace has left. Read-only; the server
 * enforces both guards regardless.
 */
export default function CostEstimate({
  delivery,
  aiEnabled,
}: {
  delivery: DeliverySettings;
  aiEnabled: boolean;
}) {
  const limits = useLimits().data;
  const est = estimateStrategyCost(Number(delivery.pollInterval), Number(delivery.cooldown), aiEnabled);
  if (!est) return null;

  const share =
    aiEnabled && limits && limits.ai_daily_budget > 0
      ? Math.round((100 * est.ai_calls_per_day_max) / limits.ai_daily_budget)
      : null;
  const atCap = !!limits && limits.strategies_remaining !== null && limits.strategies_remaining <= 0;
  const heavy = share !== null && share >= 50;

  return (
    <p className={`muted small cost-estimate ${heavy || atCap ? "warn" : ""}`} role="status">
      Evaluates up to <b>{est.evaluations_per_day}×/day</b>
      {aiEnabled ? (
        <>
          {" · "}up to <b>{est.ai_calls_per_day_max} AI calls/day</b>
          {share !== null && ` (${share}% of your ${limits!.ai_daily_budget}/day AI budget)`}
        </>
      ) : (
        " · no AI calls"
      )}
      {limits && limits.strategy_cap > 0 && (
        <>
          {" · "}
          {atCap
            ? `workspace at its cap of ${limits.strategy_cap} strategies`
            : `${limits.strategy_count} of ${limits.strategy_cap} strategies used`}
        </>
      )}
      .
    </p>
  );
}

/** True when the workspace cannot take another strategy (server enforces too). */
export function useAtStrategyCap(): boolean {
  const limits = useLimits().data;
  return !!limits && limits.strategies_remaining !== null && limits.strategies_remaining <= 0;
}
