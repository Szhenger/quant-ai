import { Fragment, useEffect, useState } from "react";
import api, { fetchAllPages } from "../api/client";
import { extractError } from "../api/errors";
import type { EvaluateResult, ReplayResult, Strategy } from "../api/types";
import StrategyForm from "./StrategyForm";
import ReplayPanel from "./ReplayPanel";

// The graph builder pulls in reactflow (~the largest thing in the bundle);
// load it only when someone actually opens the graph tab.
const StrategyGraphBuilder = lazy(() => import("./StrategyGraphBuilder"));

type Builder = "form" | "graph";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export default function StrategiesPanel() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  const strategies = useStrategies();
  const evaluate = useEvaluateStrategy();
  const remove = useDeleteStrategy();

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

  const onCreated = () => void qc.invalidateQueries({ queryKey: keys.strategies(ws) });

  const runEvaluate = (id: string) => {
    setEvalState((s) => ({ ...s, [id]: "evaluating…" }));
    evaluate.mutate(id, {
      onSuccess: (data) => setEvalState((s) => ({ ...s, [id]: data.status })),
      onError: (err) => setEvalState((s) => ({ ...s, [id]: extractError(err) })),
    });
  };

  const rows = strategies.data ?? [];
  const busyId = evaluate.isPending ? evaluate.variables : remove.isPending ? remove.variables : null;

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
          <button
            className="btn ghost"
            onClick={() => void strategies.refetch()}
            disabled={strategies.isFetching}
          >
            {strategies.isFetching ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        {strategies.isError && <div className="alert error">{extractError(strategies.error)}</div>}
        {remove.isError && <div className="alert error">{extractError(remove.error)}</div>}

        {rows.length === 0 && !strategies.isLoading ? (
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
                {rows.map((s) => {
                  const busy = busyId === s.id;
                  const open = openReplayId === s.id;
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
                            onClick={() => runEvaluate(s.id)}
                            disabled={busy}
                          >
                            Evaluate
                          </button>
                          <button
                            className="btn small"
                            onClick={() => setOpenReplayId(open ? null : s.id)}
                            title="Replay this condition over history — when would it have fired?"
                          >
                            {open ? "Hide replay" : "Replay"}
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
                            onClick={() => remove.mutate(s.id)}
                            disabled={busy}
                          >
                            Delete
                          </button>
                        </td>
                      </tr>
                      {open && (
                        <tr className="replay-row">
                          <td colSpan={7}>
                            <ReplayPanel strategyId={s.id} />
                          </td>
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
          <StrategyForm onCreated={onCreated} />
        ) : (
          <Suspense fallback={<p className="muted">Loading graph builder…</p>}>
            <StrategyGraphBuilder onCreated={onCreated} />
          </Suspense>
        )}
      </section>
    </div>
  );
}
