/**
 * estimateStrategyCost mirrors identity.limits.estimate_strategy_cost; the
 * numbers here are the same ones test_limits.py pins on the backend.
 */
import { describe, expect, it } from "vitest";
import { estimateStrategyCost } from "../../../frontend/src/contract/estimate";

describe("estimateStrategyCost", () => {
  it("matches the backend bounds", () => {
    expect(estimateStrategyCost(15, 60, false)).toEqual({
      evaluations_per_day: 96,
      ai_calls_per_day_max: 0,
    });
    expect(estimateStrategyCost(15, 60, true)?.ai_calls_per_day_max).toBe(24);
    expect(estimateStrategyCost(60, 15, true)?.ai_calls_per_day_max).toBe(24);
    expect(estimateStrategyCost(1, 1440, true)?.ai_calls_per_day_max).toBe(1);
    expect(estimateStrategyCost(7, 1440, false)?.evaluations_per_day).toBe(206);
  });

  it("is null until the inputs are valid whole minutes", () => {
    expect(estimateStrategyCost(0, 60, true)).toBeNull();
    expect(estimateStrategyCost(15, Number.NaN, true)).toBeNull();
    expect(estimateStrategyCost(2.5, 60, true)).toBeNull();
  });
});
