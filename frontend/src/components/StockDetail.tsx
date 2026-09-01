import { FormEvent, useEffect, useState } from "react";
import { extractError } from "../api/errors";
import {
  useStockPage,
  useStockHistory,
  useRefreshStockPage,
  useUpdateWatch,
} from "../api/hooks";
import type { WatchedTicker } from "../api/types";
import LineChart from "./LineChart";

function num(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function sinceLabel(iso: string | null): string {
  if (!iso) return "not yet";
  const ms = Date.now() - new Date(iso).getTime();
  const h = Math.floor(ms / 3_600_000);
  if (h < 1) return "just now";
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function pubLabel(v: string | number | null): string {
  if (v == null) return "";
  const d = typeof v === "number" ? new Date(v * 1000) : new Date(v);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString();
}

export default function StockDetail({
  watch,
  onCreateAlert,
}: {
  watch: WatchedTicker;
  onCreateAlert?: (ticker: string) => void;
}) {
  const pageQ = useStockPage(watch.id);
  const history = useStockHistory(watch.id);
  const refresh = useRefreshStockPage();
  const updateWatch = useUpdateWatch();

  // Interval bounds mirror the backend model validators.
  const N_MAX = 720; // 30 days
  const M_MAX = 2160; // 90 days

  const [n, setN] = useState(String(watch.refresh_interval_hours));
  const [m, setM] = useState(String(watch.recompute_interval_hours));
  useEffect(() => {
    setN(String(watch.refresh_interval_hours));
    setM(String(watch.recompute_interval_hours));
  }, [watch.id, watch.refresh_interval_hours, watch.recompute_interval_hours]);

  const clamp = (v: string, max: number) => Math.min(max, Math.max(1, Number(v) || 1));
  const onSaveCadence = (e: FormEvent) => {
    e.preventDefault();
    updateWatch.mutate({
      id: watch.id,
      body: {
        refresh_interval_hours: clamp(n, N_MAX),
        recompute_interval_hours: clamp(m, M_MAX),
      },
    });
  };

  const d = pageQ.data?.page ?? null;
  const computing = !!pageQ.data && !pageQ.data.ready;
  // A refresh in flight: the page on screen is the last compiled one and the
  // hook is polling for its replacement.
  const refreshing = refresh.isPending || !!d?.refreshing;

  return (
    <section className="card stock-detail">
      <div className="stock-detail-head">
        <div>
          <div className="analysis-ticker">
            {watch.ticker}
            {d?.data_synthetic && (
              <span className="badge synthetic" title="Compiled from synthetic fallback data, not real market data">
                SYNTHETIC
              </span>
            )}
          </div>
          {d && (
            <div className="muted small">
              News refreshed {sinceLabel(d.refreshed_at)} · measures recomputed{" "}
              {sinceLabel(d.recomputed_at)}
            </div>
          )}
        </div>
        <div className="row gap">
          {onCreateAlert && (
            <button className="btn" onClick={() => onCreateAlert(watch.ticker)}>
              Set an alert
            </button>
          )}
          <button
            className="btn primary"
            onClick={() => refresh.mutate(watch.id)}
            disabled={refreshing}
          >
            {refreshing ? "Refreshing…" : "Refresh now"}
          </button>
        </div>
      </div>

      {(pageQ.isLoading || computing) && (
        <p className="muted">Compiling this week's financial data…</p>
      )}
      {d && refreshing && (
        <p className="muted small" role="status">
          Recompiling in the background — the numbers below update automatically when
          it finishes.
        </p>
      )}
      {pageQ.isError && <div className="alert error">{extractError(pageQ.error)}</div>}
      {refresh.isError && <div className="alert error">{extractError(refresh.error)}</div>}

      {d && (
        <>
          {/* ---- Quantitative measure: summary then full detail ---- */}
          <div className="measure-block">
            <div className="measure-title">
              <h3>Quantitative</h3>
              <span className="muted small">the numbers, over a macro window</span>
            </div>
            <p className="measure-headline">{d.quantitative_summary.headline}</p>
            <div className="chips">
              {d.quantitative_summary.measures.map((mm) => (
                <span className="chip" key={mm.key} title={`${mm.label} = ${num(mm.value, 4)} ${mm.unit}`}>
                  <b>{mm.label}</b> {num(mm.value, 2)}
                  {mm.unit} — {mm.reading}
                </span>
              ))}
            </div>
            <div className="chart-frame">
              <LineChart values={d.quantitative.week.closes} labels={d.quantitative.week.dates} />
            </div>
            <details>
              <summary className="muted small">Full indicator detail</summary>
              <table className="table">
                <thead>
                  <tr>
                    <th>Indicator</th>
                    <th className="num">Value</th>
                    <th>Unit</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(d.quantitative.indicators).map(([key, val]) => (
                    <tr key={key}>
                      <td>{val ? val.label : key}</td>
                      <td className="num">{num(val ? val.value : null, 4)}</td>
                      <td className="muted">{val?.unit || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          </div>

          {/* ---- Qualitative measure: Claude summary then the headlines ---- */}
          <div className="measure-block">
            <div className="measure-title">
              <h3>Qualitative</h3>
              <span className="muted small">
                this week's news · {d.qualitative.summary_source === "claude" ? "summarized by Claude" : "AI summary unavailable"}
              </span>
            </div>
            <p className="measure-summary">{d.qualitative.summary}</p>
            {d.qualitative.news.length === 0 ? (
              <p className="muted small">No headlines found for this company this week.</p>
            ) : (
              <ul className="news-list">
                {d.qualitative.news.map((item, i) => (
                  <li key={i}>
                    <span className="news-title">{item.title}</span>
                    <span className="muted small">
                      {" "}
                      {item.source}
                      {pubLabel(item.published_at) && ` · ${pubLabel(item.published_at)}`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* ---- Cadence controls (n / m) ---- */}
          <form className="cadence" onSubmit={onSaveCadence}>
            <div className="measure-title">
              <h3>Update schedule</h3>
              <span className="muted small">how often QuantAI recompiles this page</span>
            </div>
            <div className="row gap wrap">
              <label className="field">
                Refresh news every
                <span className="row gap tight">
                  <input type="number" min={1} max={N_MAX} value={n} onChange={(e) => setN(e.target.value)} aria-label="Refresh interval (hours)" />
                  <span className="muted">hours (n)</span>
                </span>
              </label>
              <label className="field">
                Recompute measures every
                <span className="row gap tight">
                  <input type="number" min={1} max={M_MAX} value={m} onChange={(e) => setM(e.target.value)} aria-label="Recompute interval (hours)" />
                  <span className="muted">hours (m)</span>
                </span>
              </label>
              <button className="btn" type="submit" disabled={updateWatch.isPending}>
                {updateWatch.isPending ? "Saving…" : "Save schedule"}
              </button>
            </div>
            <p className="muted small">Up to {N_MAX}h (30d) for news, {M_MAX}h (90d) for measures.</p>
            {updateWatch.isError && (
              <div className="alert error">{extractError(updateWatch.error)}</div>
            )}
          </form>

          {/* ---- Continuity: retained prior measures ---- */}
          {(history.data?.snapshots?.length ?? 0) > 0 && (
            <div className="measure-block">
              <div className="measure-title">
                <h3>Continuity</h3>
                <span className="muted small">retained prior measures (compressed)</span>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Taken</th>
                    <th className="num">Latest price</th>
                    <th className="num">Week change</th>
                  </tr>
                </thead>
                <tbody>
                  {history.data!.snapshots.map((s, i) => (
                    <tr key={i}>
                      <td className="muted">{new Date(s.taken_at).toLocaleString()}</td>
                      <td className="num">{num(s.summary?.latest_price ?? null, 2)}</td>
                      <td className="num">{num(s.summary?.week_change_pct ?? null, 2)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
