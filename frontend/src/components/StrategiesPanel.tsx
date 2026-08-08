import { useEffect, useState } from "react";
import api from "../api/client";
import { extractError } from "../api/errors";
import type { EvaluateResult, Paginated, Strategy } from "../api/types";
import StrategyForm from "./StrategyForm";
import StrategyGraphBuilder from "./StrategyGraphBuilder";

type Builder = "form" | "graph";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export default function StrategiesPanel() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [builder, setBuilder] = useState<Builder>("form");

  const [evalState, setEvalState] = useState<Record<string, string>>({});
  const [rowBusy, setRowBusy] = useState<Record<string, boolean>>({});

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<Paginated<Strategy>>("/strategies/");
      setStrategies(res.data.results);
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
                {strategies.map((s) => (
                  <tr key={s.id}>
                    <td>
                      {s.name}
                      {s.ai_enabled && <span className="badge ai">AI</span>}
                    </td>
                    <td>{s.ticker}</td>
                    <td className="mono">
                      {s.indicator} {s.operator} {s.threshold}
                    </td>
                    <td>
                      <span className="badge status">{s.status}</span>
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
                        className="btn small danger"
                        onClick={() => void remove(s.id)}
                        disabled={rowBusy[s.id]}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
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
