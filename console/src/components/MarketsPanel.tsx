import { FormEvent, useState } from "react";
import { extractError } from "../api/errors";
import { useAddWatch, useAnalysis, useRemoveWatch, useWatchlist } from "../api/hooks";
import LineChart from "./LineChart";

function formatValue(v: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

export default function MarketsPanel() {
  // `input` is what the user is typing; `ticker` is the committed symbol the
  // analysis query keys on. Re-clicking a cached ticker renders instantly from
  // cache while React Query revalidates in the background.
  const [input, setInput] = useState("AAPL");
  const [ticker, setTicker] = useState("AAPL");
  const [newTicker, setNewTicker] = useState("");
  const [newNote, setNewNote] = useState("");

  const analysis = useAnalysis(ticker);
  const watchlist = useWatchlist();
  const addWatch = useAddWatch();
  const removeWatch = useRemoveWatch();

  const commit = (symbol: string) => {
    const sym = symbol.trim().toUpperCase();
    if (!sym) return;
    setInput(sym);
    setTicker(sym);
  };

  const onAnalyze = (e: FormEvent) => {
    e.preventDefault();
    commit(input);
  };

  const onAddWatch = (e: FormEvent) => {
    e.preventDefault();
    const t = newTicker.trim().toUpperCase();
    if (!t) return;
    addWatch.mutate(
      { ticker: t, note: newNote.trim() },
      {
        onSuccess: () => {
          setNewTicker("");
          setNewNote("");
        },
      },
    );
  };

  const data = analysis.data;
  const indicatorRows = data
    ? Object.entries(data.indicators).map(([key, val]) => ({ key, val }))
    : [];

  return (
    <div className="grid-2">
      <section className="card">
        <h2 className="card-title">Market analysis</h2>
        <form className="row gap" onSubmit={onAnalyze}>
          <input
            className="grow"
            value={input}
            onChange={(e) => setInput(e.target.value.toUpperCase())}
            placeholder="Ticker e.g. AAPL"
            aria-label="Ticker"
          />
          <button className="btn primary" type="submit" disabled={analysis.isLoading}>
            {analysis.isFetching ? "Analyzing…" : "Analyze"}
          </button>
        </form>

        {analysis.isError && <div className="alert error">{extractError(analysis.error)}</div>}

        {data && (
          <>
            <div className="analysis-head">
              <div>
                <div className="analysis-ticker">
                  {data.ticker}
                  {data.synthetic && (
                    <span
                      className="badge synthetic"
                      title="Computed from synthetic fallback data, not real market data"
                    >
                      SYNTHETIC
                    </span>
                  )}
                </div>
                <div className="muted">via {data.provider}</div>
                {data.synthetic && (
                  <div className="muted small">
                    Simulated data — real quotes unavailable for this symbol (check the
                    ticker).
                  </div>
                )}
              </div>
              <div className="analysis-price">
                <div className="muted">Latest price</div>
                <div className="price-value">
                  {data.latest_price?.toLocaleString(undefined, {
                    maximumFractionDigits: 2,
                  })}
                </div>
              </div>
            </div>

            <div className="chart-frame">
              <LineChart values={data.closes} labels={data.dates} />
            </div>

            <table className="table">
              <thead>
                <tr>
                  <th>Indicator</th>
                  <th className="num">Value</th>
                  <th>Unit</th>
                </tr>
              </thead>
              <tbody>
                {indicatorRows.map(({ key, val }) => (
                  <tr key={key}>
                    <td>{val ? val.label : key}</td>
                    <td className="num">{formatValue(val ? val.value : null)}</td>
                    <td className="muted">{val?.unit || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        {!data && !analysis.isLoading && !analysis.isError && (
          <p className="muted">Enter a ticker and press Analyze.</p>
        )}
      </section>

      <section className="card">
        <h2 className="card-title">Watchlist</h2>
        <form className="row gap wrap" onSubmit={onAddWatch}>
          <input
            className="grow"
            value={newTicker}
            onChange={(e) => setNewTicker(e.target.value.toUpperCase())}
            placeholder="Ticker"
            aria-label="Watchlist ticker"
          />
          <input
            className="grow"
            value={newNote}
            onChange={(e) => setNewNote(e.target.value)}
            placeholder="Note (optional)"
            aria-label="Watchlist note"
          />
          <button className="btn" type="submit" disabled={addWatch.isPending}>
            {addWatch.isPending ? "Adding…" : "Add"}
          </button>
        </form>

        {(watchlist.isError || addWatch.isError) && (
          <div className="alert error">
            {extractError(watchlist.error ?? addWatch.error)}
          </div>
        )}

        {(watchlist.data ?? []).length === 0 ? (
          <p className="muted">No tickers followed yet.</p>
        ) : (
          <ul className="watchlist">
            {(watchlist.data ?? []).map((w) => (
              <li key={w.id} className="watchlist-row">
                <button className="link-ticker" onClick={() => commit(w.ticker)}>
                  {w.ticker}
                </button>
                {w.note && <span className="muted"> — {w.note}</span>}
                <button
                  className="btn small ghost watch-remove"
                  onClick={() => removeWatch.mutate(w.id)}
                  disabled={removeWatch.isPending && removeWatch.variables === w.id}
                  title={`Stop following ${w.ticker}`}
                  aria-label={`Remove ${w.ticker} from watchlist`}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
