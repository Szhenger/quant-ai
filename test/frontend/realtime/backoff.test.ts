import { describe, expect, it } from "vitest";
import { reconnectDelayMs } from "../../../frontend/src/realtime/backoff";

describe("reconnectDelayMs", () => {
  it("grows exponentially at the jitter ceiling", () => {
    const maxRandom = () => 1;
    expect(reconnectDelayMs(0, maxRandom)).toBe(1_000);
    expect(reconnectDelayMs(1, maxRandom)).toBe(2_000);
    expect(reconnectDelayMs(2, maxRandom)).toBe(4_000);
    expect(reconnectDelayMs(3, maxRandom)).toBe(8_000);
  });

  it("caps at 30s no matter how many attempts", () => {
    const maxRandom = () => 1;
    expect(reconnectDelayMs(10, maxRandom)).toBe(30_000);
    expect(reconnectDelayMs(100, maxRandom)).toBe(30_000);
    expect(reconnectDelayMs(10_000, maxRandom)).toBe(30_000);
  });

  it("jitters down to half the exponential step, never below", () => {
    const minRandom = () => 0;
    expect(reconnectDelayMs(0, minRandom)).toBe(500);
    expect(reconnectDelayMs(3, minRandom)).toBe(4_000);
    expect(reconnectDelayMs(100, minRandom)).toBe(15_000);
  });

  it("spreads real clients across the window (no lockstep reconnect)", () => {
    const delays = new Set<number>();
    for (let i = 0; i < 50; i++) {
      delays.add(reconnectDelayMs(4));
    }
    // 50 draws over a 4-8s window collapsing to a handful of values would
    // indicate broken jitter.
    expect(delays.size).toBeGreaterThan(10);
    for (const d of delays) {
      expect(d).toBeGreaterThanOrEqual(8_000);
      expect(d).toBeLessThanOrEqual(16_000);
    }
  });
});
