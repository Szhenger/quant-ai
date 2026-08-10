import { Fragment, useEffect, useState } from "react";
import api, { fetchAllPages } from "../api/client";
import { extractError } from "../api/errors";
import type { EvaluateResult, ReplayResult, Strategy } from "../api/types";
import StrategyForm from "./StrategyForm";
import StrategyGraphBuilder from "./StrategyGraphBuilder";

type Builder = "form" | "graph";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function renderReplay(rep: ReplayResult | { error: string }) {
  if ("error" in rep) {
    return <span className="alert error">Replay failed: {rep.error}</span>;
  }
  const recent = rep.fires.slice(-6).reverse();
  return (
    <div className="replay-summary">
      <div className="replay-head">
        <strong>Signal replay</strong> — <span className="mono">{rep.condition}</span> would have
        fired <strong>{rep.fire_count}</strong> {rep.fire_count === 1 ? "time" : "times"} over{" "}
        {rep.bars} bars.
        {rep.synthetic && (
          <span className="badge synthetic" title="Replayed on synthetic fallback data, not real market data">
            SYNTHETIC
          </span>
        )}
      </div>
      {recent.length > 0 && (
        <div className="replay-fires muted small">
          Most recent:{" "}
          {recent.map((f) => (f.date ? f.date.slice(0, 10) : `bar ${f.index}`)).join(" · ")}
        </div>
      )}
    </div>
  );
}

export default function StrategiesPanel() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [builder, setBuilder] = useState<Builder>("form");

  const [evalState, setEvalState] = useState<Record<string, string>>({});
  const [rowBusy, setRowBusy] = useState<Record<string, boolean>>({});
  const [replay, setReplay] = useState<Record<string, ReplayResult | { error: string }>>({});

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setStrategies(await fetchAllPages<Strategy>("/strategies/"));
    } catch (err) {
      setError(extractError(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const evaluate = async (id: string) => {
    setRowBusy((s) => ({ ...s, [id]: true }));
    setEvalState((s) => ({ ...s, [id]: "evaluating…" }));
    try {
      const res = await api.post<EvaluateResult>(`/strategies/${id}/evaluate/`);
      setEvalState((s) => ({ ...s, [id]: res.data.status }));
      await load();
    } catch (err) {
      setEvalState((s) => ({ ...s, [id]: extractError(err) }));
    } finally {
      setRowBusy((s) => ({ ...s, [id]: false }));
    }
  };

  const runReplay = async (id: string) => {
    setRowBusy((s) => ({ ...s, [id]: true }));
    try {
      const res = await api.post<ReplayResult>(`/strategies/${id}/replay/`, { days: 365 });
      setReplay((s) => ({ ...s, [id]: res.data }));
    } catch (err) {
      setReplay((s) => ({ ...s, [id]: { error: extractError(err) } }));
    } finally {
      setRowBusy((s) => ({ ...s, [id]: false }));
    }
  };

  const remove = async (id: string) => {
    setRowBusy((s) => ({ ...s, [id]: true }));
    try {
      await api.delete(`/strategies/${id}/`);
      await load();
    } catch (err) {
      setError(extractError(err));
    } finally {
      setRowBusy((s) => ({ ...s, [id]: false }));
    }
  };

  // Reactivate a strategy the failure circuit breaker paused.
  const resume = async (id: string) => {
    setRowBusy((s) => ({ ...s, [id]: true }));
    try {
      await api.patch(`/strategies/${id}/`, { status: "active" });
      await load();
    } catch (err) {
      setError(extractError(err));
    } finally {
      setRowBusy((s) => ({ ...s, [id]: false }));
    }
  };

  return (
    <div className="stack">
      <section className="card">
        <div className="card-head">
          <h2 className="card-title">Strategies</h2>
          <button className="btn ghost" onClick={() => void load()} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        {error && <div className="alert error">{error}</div>}

        {strategies.length === 0 && !loading ? (
          <p className="muted">No strategies yet. Create one below.</p>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Ticker</th>
                  <th>Condition</th>
                  <th>Status</th>
                  <th>Last triggered</th>
                  <th>Result</th>
                  <th className="num">Actions</th>
                </tr>
              </thead>
              <tbody>
                {strategies.map((s) => {
                  const rep = replay[s.id];
                  return (
                    <Fragment key={s.id}>
                      <tr>
                        <td>
                          {s.name}
                          {s.ai_enabled && <span className="badge ai">AI</span>}
                          {s.condition != null && <span className="badge status">composite</span>}
                        </td>
                        <td>{s.ticker}</td>
                        <td className="mono">
                          {s.indicator} {s.operator} {s.threshold}
                        </td>
                        <td>
                          <span className="badge status" title={s.last_error || undefined}>
                            {s.status}
                          </span>
                        </td>
                        <td className="muted">{formatDate(s.last_triggered_at)}</td>
                        <td className="muted">{evalState[s.id] ?? "—"}</td>
                        <td className="num actions">
                          <button
                            className="btn small"
                            onClick={() => void evaluate(s.id)}
                            disabled={rowBusy[s.id]}
                          >
                            Evaluate
                          </button>
                          <button
                            className="btn small"
                            onClick={() => void runReplay(s.id)}
                            disabled={rowBusy[s.id]}
                            title="Replay this condition over history — when would it have fired?"
                          >
                            Replay
                          </button>
                          {s.status === "failed" && (
                            <button
                              className="btn small"
                              onClick={() => void resume(s.id)}
                              disabled={rowBusy[s.id]}
                              title="Reactivate this strategy and re-arm its failure circuit breaker"
                            >
                              Resume
                            </button>
                          )}
                          <button
                            className="btn small danger"
                            onClick={() => void remove(s.id)}
                            disabled={rowBusy[s.id]}
                          >
                            Delete
                          </button>
                        </td>
                      </tr>
                      {rep && (
                        <tr className="replay-row">
                          <td colSpan={7}>{renderReplay(rep)}</td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2 className="card-title">New strategy</h2>
          <div className="toggle">
            <button
              className={`toggle-btn ${builder === "form" ? "active" : ""}`}
              onClick={() => setBuilder("form")}
            >
              Form
            </button>
            <button
              className={`toggle-btn ${builder === "graph" ? "active" : ""}`}
              onClick={() => setBuilder("graph")}
            >
              Graph builder
            </button>
          </div>
        </div>

        {builder === "form" ? (
          <StrategyForm onCreated={() => void load()} />
        ) : (
          <StrategyGraphBuilder onCreated={() => void load()} />
        )}
      </section>
    </div>
  );
}
