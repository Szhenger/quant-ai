import { FormEvent, useState } from "react";
import { extractError } from "../api/errors";
import { useReplay } from "../api/hooks";
import ReplayChart from "./ReplayChart";

const DAY_CHOICES = [90, 180, 365, 730, 1000];

interface ReplayPanelProps {
  strategyId: string;
  /** The strategy's live cooldown, used to seed an equivalent bar cooldown. */
  liveCooldownMinutes?: number;
}

/**
 * Signal replay for one strategy: when would this condition have fired?
 * Deterministic and side-effect free — a would-fire timeline, not a backtest.
 * Window/cooldown changes keep the previous chart on screen while the next
 * result loads (and usually land instantly from the server's compute cache).
 */
export default function ReplayPanel({ strategyId, liveCooldownMinutes }: ReplayPanelProps) {
  const [days, setDays] = useState(365);
  // Seed from the live cooldown so the fire count approximates what the live
  // strategy would do — a 0-bar default systematically overstates it. Bars are
  // daily, live cooldown is minutes: 1 bar ≈ 1440 min.
  const seededBars =
    liveCooldownMinutes != null
      ? Math.max(0, Math.min(365, Math.ceil(liveCooldownMinutes / 1440)))
      : 0;
  const [cooldownInput, setCooldownInput] = useState(String(seededBars));
  const [cooldownBars, setCooldownBars] = useState(seededBars);

  const replay = useReplay(strategyId, days, cooldownBars);

  const applyCooldown = (e: FormEvent) => {
    e.preventDefault();
    const n = Number(cooldownInput);
    if (Number.isFinite(n)) {
      setCooldownBars(Math.max(0, Math.min(365, Math.round(n))));
    }
  };

  const rep = replay.data;

  return (
    <div className="replay-summary">
      <div className="row gap wrap replay-controls">
        <label className="muted small">
          Window{" "}
          <select
            className="ws-select"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            {DAY_CHOICES.map((d) => (
              <option key={d} value={d}>
                {d} days
              </option>
            ))}
          </select>
        </label>
        <form className="row gap" onSubmit={applyCooldown}>
          <label className="muted small">
            Cooldown (bars){" "}
            <input
              className="replay-cooldown"
              value={cooldownInput}
              onChange={(e) => setCooldownInput(e.target.value)}
              inputMode="numeric"
              aria-label="Cooldown bars"
            />
          </label>
          <button className="btn small" type="submit">
            Apply
          </button>
        </form>
        {replay.isFetching && <span className="muted small">replaying…</span>}
        <span className="muted small">
          Replay cooldown counts daily bars; the live cooldown is minutes (1 bar ≈ 1440
          min).
        </span>
      </div>

      {replay.isError && (
        <div className="alert error">Replay failed: {extractError(replay.error)}</div>
      )}

      {rep && (
        <>
          <div className="replay-head">
            <strong>Signal replay</strong> — <span className="mono">{rep.condition}</span> would
            have fired <strong>{rep.fire_count}</strong>{" "}
            {rep.fire_count === 1 ? "time" : "times"} over {rep.bars} bars.
            {rep.synthetic && (
              <span
                className="badge synthetic"
                title="Replayed on synthetic fallback data, not real market data"
              >
                SYNTHETIC
              </span>
            )}
          </div>
          <div className="chart-frame">
            <ReplayChart closes={rep.closes} dates={rep.dates} fires={rep.fires} />
          </div>
          {rep.fires.length > 0 && (
            <div className="replay-fires muted small">
              Most recent:{" "}
              {rep.fires
                .slice(-6)
                .reverse()
                .map((f) => (f.date ? f.date.slice(0, 10) : `bar ${f.index}`))
                .join(" · ")}
            </div>
          )}
        </>
      )}
    </div>
  );
}
