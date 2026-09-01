import { Fragment, Suspense, lazy, useEffect, useState } from "react";
import { extractError } from "../api/errors";
import {
  useDeleteStrategy,
  useEvaluateStrategy,
  useLimits,
  useStrategies,
  useUpdateStrategy,
} from "../api/hooks";
import { useRealtimeStore } from "../realtime/store";
import StrategyForm from "./StrategyForm";
import StrategyEditor from "./StrategyEditor";
import ReplayPanel from "./ReplayPanel";
import type { EvaluateResult } from "../api/types";

// The graph builder pulls in reactflow (~the largest thing in the bundle);
// load it only when someone actually opens the graph tab.
const StrategyGraphBuilder = lazy(() => import("./StrategyGraphBuilder"));

type Builder = "form" | "graph";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

interface EvalDisplay {
  text: string;
  title?: string;
}

const EVALUATING_TEXT = "evaluating…";
const QUEUED_TEXT = "Queued — result arrives when the worker finishes";

/** Human copy for the raw evaluate statuses the API returns. */
function describeEvalResult(data: EvaluateResult): EvalDisplay {
  switch (data.status) {
    case "alerted":
      return { text: "Alert fired" };
    case "quant_not_met":
      return {
        text:
          typeof data.value === "number"
            ? `Condition not met (value ${data.value.toFixed(2)})`
            : "Condition not met",
      };
    case "cooldown":
      return { text: "In cooldown" };
    case "ai_suppressed":
      return {
        text: "AI advised no alert",
        title: typeof data.rationale === "string" ? data.rationale : undefined,
      };
    case "locked":
      return { text: "Already evaluating" };
    case "queued":
      return { text: QUEUED_TEXT };
    case "error":
      return { text: typeof data.error === "string" ? data.error : "error" };
    default:
      return { text: data.status };
  }
}

export default function StrategiesPanel({ initialTicker }: { initialTicker?: string } = {}) {
  const strategies = useStrategies();
  const limits = useLimits().data;
  const evaluate = useEvaluateStrategy();
  const remove = useDeleteStrategy();

  const updateStrategy = useUpdateStrategy();

  const [builder, setBuilder] = useState<Builder>("form");
  const [evalState, setEvalState] = useState<Record<string, EvalDisplay>>({});
  const [openReplayId, setOpenReplayId] = useState<string | null>(null);
  const [openEditId, setOpenEditId] = useState<string | null>(null);
  // Two-step delete: first click arms this id, second click within the window
  // actually deletes. Prevents losing a strategy to one stray click.
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // Circuit-breaker notices pushed over the WebSocket (strategy_status frames).
  const strategyNotice = useRealtimeStore((s) => s.strategyNotice);
  const setStrategyNotice = useRealtimeStore((s) => s.setStrategyNotice);
  // Outcomes of worker-side evaluations (`strategy.evaluated` events): a
  // "Queued" cell resolves into the real result the moment the worker is done.
  const evaluations = useRealtimeStore((s) => s.evaluations);
  useEffect(() => {
    setEvalState((s) => {
      let next = s;
      for (const [id, result] of Object.entries(evaluations)) {
        const cell = s[id];
        if (cell && (cell.text === QUEUED_TEXT || cell.text === EVALUATING_TEXT)) {
          next = { ...next, [id]: describeEvalResult(result) };
        }
      }
      return next;
    });
  }, [evaluations]);

  const clearEval = (id: string) =>
    setEvalState((s) => {
      if (!(id in s)) return s;
      const { [id]: _dropped, ...rest } = s;
      return rest;
    });

  const runEvaluate = (id: string) => {
    setEvalState((s) => ({ ...s, [id]: { text: EVALUATING_TEXT } }));
    evaluate.mutate(id, {
      // A "Queued" cell is replaced by the worker's outcome when its
      // `strategy.evaluated` event lands (see the effect above).
      onSuccess: (data) => setEvalState((s) => ({ ...s, [id]: describeEvalResult(data) })),
      onError: (err) => setEvalState((s) => ({ ...s, [id]: { text: extractError(err) } })),
    });
  };

  // Pause/resume — also how a FAILED strategy is reactivated (re-arms the
  // failure circuit breaker server-side).
  const setStatus = (id: string, status: "active" | "paused") => {
    updateStrategy.mutate(
      { id, patch: { status } },
      {
        onError: (err) => setEvalState((s) => ({ ...s, [id]: { text: extractError(err) } })),
        // The row changed identity (paused/reactivated): a stale eval result
        // no longer describes it.
        onSuccess: () => clearEval(id),
      },
    );
  };

  const onDeleteClick = (id: string) => {
    if (confirmDeleteId !== id) {
      setConfirmDeleteId(id);
      setTimeout(() => setConfirmDeleteId((c) => (c === id ? null : c)), 4000);
      return;
    }
    setConfirmDeleteId(null);
    remove.mutate(id, { onSuccess: () => clearEval(id) });
  };

  const rows = strategies.data ?? [];
  // Separate busy tracking per mutation: a pending delete must not re-enable
  // (or disable) another row's Evaluate button and vice versa.
  const evalBusyId = evaluate.isPending ? evaluate.variables : null;
  const deleteBusyId = remove.isPending ? remove.variables : null;

  return (
    <div className="stack">
      <section className="card">
        <div className="card-head">
          <h2 className="card-title">Strategies</h2>
          <div className="row gap">
            {limits && (
              <span className="muted small" title="Account guards: strategy cap and daily AI-call budget (resets at UTC midnight)">
                {limits.strategy_cap > 0
                  ? `${limits.strategy_count} of ${limits.strategy_cap} strategies`
                  : `${limits.strategy_count} strategies`}
                {" · "}AI calls today {limits.ai_calls_today} of {limits.ai_daily_budget}
              </span>
            )}
            <button
              className="btn ghost"
              onClick={() => void strategies.refetch()}
              disabled={strategies.isFetching}
            >
              {strategies.isFetching ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        </div>

        {strategyNotice && (
          <div className="alert error">
            {strategyNotice}{" "}
            <button className="btn small ghost" onClick={() => setStrategyNotice(null)}>
              Dismiss
            </button>
          </div>
        )}
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
                  const busy = evalBusyId === s.id || deleteBusyId === s.id;
                  const open = openReplayId === s.id;
                  const editing = openEditId === s.id;
                  const armed = confirmDeleteId === s.id;
                  return (
                    <Fragment key={s.id}>
                      <tr>
                        <td>
                          {s.name}
                          {s.ai_enabled && <span className="badge ai">AI</span>}
                          {s.condition != null && <span className="badge status">composite</span>}
                        </td>
                        <td>{s.ticker}</td>
                        <td>
                          {/* The real firing rule — for composites the flat
                              columns only hold a representative leaf. */}
                          <span className="mono">
                            {s.condition_summary || `${s.indicator} ${s.operator} ${s.threshold}`}
                          </span>
                          <div className="muted small">
                            {s.cost_estimate.evaluations_per_day} evals/day
                            {s.ai_enabled && ` · ≤${s.cost_estimate.ai_calls_per_day_max} AI/day`}
                          </div>
                        </td>
                        <td>
                          <span className="badge status" title={s.last_error || undefined}>
                            {s.status}
                          </span>
                        </td>
                        <td className="muted">{formatDate(s.last_triggered_at)}</td>
                        <td className="muted" title={evalState[s.id]?.title}>
                          {evalState[s.id]?.text ?? "—"}
                        </td>
                        <td className="num actions">
                          <button
                            className="btn small"
                            onClick={() => runEvaluate(s.id)}
                            disabled={evalBusyId === s.id}
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
                          <button
                            className="btn small"
                            onClick={() => setOpenEditId(editing ? null : s.id)}
                          >
                            {editing ? "Close" : "Edit"}
                          </button>
                          {s.status === "active" ? (
                            <button
                              className="btn small"
                              onClick={() => setStatus(s.id, "paused")}
                              disabled={busy}
                              title="Stop scheduled evaluations without losing the strategy"
                            >
                              Pause
                            </button>
                          ) : (
                            <button
                              className="btn small"
                              onClick={() => setStatus(s.id, "active")}
                              disabled={busy}
                              title={
                                s.status === "failed"
                                  ? "Reactivate and re-arm the failure circuit breaker"
                                  : "Resume scheduled evaluations"
                              }
                            >
                              Resume
                            </button>
                          )}
                          <button
                            className="btn small danger"
                            onClick={() => onDeleteClick(s.id)}
                            disabled={deleteBusyId === s.id}
                            title={armed ? "Click again to permanently delete" : undefined}
                          >
                            {armed ? "Confirm?" : "Delete"}
                          </button>
                        </td>
                      </tr>
                      {open && (
                        <tr className="replay-row">
                          <td colSpan={7}>
                            <ReplayPanel
                              strategyId={s.id}
                              liveCooldownMinutes={s.cooldown_minutes}
                            />
                          </td>
                        </tr>
                      )}
                      {editing && (
                        <tr className="replay-row">
                          <td colSpan={7}>
                            <StrategyEditor
                              strategy={s}
                              onClose={() => {
                                setOpenEditId(null);
                                // An edit may have changed what the rule means;
                                // don't keep describing the old one.
                                clearEval(s.id);
                              }}
                            />
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

        {/* Both builders invalidate the strategies list themselves via their
            mutation hooks, so a new row appears above without a callback. */}
        {builder === "form" ? (
          <StrategyForm initialTicker={initialTicker} />
        ) : (
          <Suspense fallback={<p className="muted">Loading graph builder…</p>}>
            <StrategyGraphBuilder />
          </Suspense>
        )}
      </section>
    </div>
  );
}
