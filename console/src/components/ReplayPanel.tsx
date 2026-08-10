import { FormEvent, useState } from "react";
import { extractError } from "../api/errors";
import { useReplay } from "../api/hooks";
import ReplayChart from "./ReplayChart";

const DAY_CHOICES = [90, 180, 365, 730, 1000];

interface ReplayPanelProps {
  strategyId: string;
}

/**
 * Signal replay for one strategy: when would this condition have fired?
 * Deterministic and side-effect free — a would-fire timeline, not a backtest.
 * Window/cooldown changes keep the previous chart on screen while the next
 * result loads (and usually land instantly from the server's compute cache).
 */
export default function ReplayPanel({ strategyId }: ReplayPanelProps) {
  const [days, setDays] = useState(365);
  const [cooldownInput, setCooldownInput] = useState("0");
  const [cooldownBars, setCooldownBars] = useState(0);

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
