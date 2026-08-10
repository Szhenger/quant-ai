/**
 * Reconnect pacing: capped exponential backoff with full jitter.
 *
 * Exponential, so a dead server isn't hammered; capped, so recovery is never
 * more than ~30s away; jittered, so a fleet of clients that all lost the same
 * server don't reconnect in lockstep and stampede it the moment it returns.
 */
const BASE_MS = 1_000;
const CAP_MS = 30_000;

export function reconnectDelayMs(attempt: number, random: () => number = Math.random): number {
  const exp = Math.min(CAP_MS, BASE_MS * 2 ** Math.min(attempt, 10));
  // Full jitter over [exp/2, exp]: keeps a floor (no thundering micro-retries)
  // while decorrelating clients.
  return Math.round(exp / 2 + (exp / 2) * random());
}
