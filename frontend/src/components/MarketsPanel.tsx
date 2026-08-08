import { FormEvent, useEffect, useState } from "react";
import api from "../api/client";
import { extractError } from "../api/errors";
import type { MarketAnalysis, Paginated, WatchedTicker } from "../api/types";
import LineChart from "./LineChart";

function formatValue(v: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

export default function MarketsPanel() {
  const [ticker, setTicker] = useState("AAPL");
  const [analysis, setAnalysis] = useState<MarketAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [watchlist, setWatchlist] = useState<WatchedTicker[]>([]);
  const [wlError, setWlError] = useState<string | null>(null);
  const [newTicker, setNewTicker] = useState("");
  const [newNote, setNewNote] = useState("");
  const [addingWatch, setAddingWatch] = useState(false);

  const loadWatchlist = async () => {
    setWlError(null);
    try {
      const res = await api.get<Paginated<WatchedTicker>>("/watchlist/");
      setWatchlist(res.data.results);
    } catch (err) {
      setWlError(extractError(err));
    }
  };

  useEffect(() => {
    loadWatchlist();
    // Kick off an initial analysis for a friendlier first view.
    void analyze("AAPL");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const analyze = async (symbol: string) => {
    const sym = symbol.trim().toUpperCase();
    if (!sym) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<MarketAnalysis>(
        `/markets/${encodeURIComponent(sym)}/analysis/`,
        { params: { days: 180 } },
      );
      setAnalysis(res.data);
      setTicker(sym);
    } catch (err) {
      setError(extractError(err));
      setAnalysis(null);
    } finally {
      setLoading(false);
    }
  };

  const onAnalyze = (e: FormEvent) => {
    e.preventDefault();
    void analyze(ticker);
  };

  const onAddWatch = async (e: FormEvent) => {
    e.preventDefault();
    const t = newTicker.trim().toUpperCase();
    if (!t) return;
    setAddingWatch(true);
    setWlError(null);
    try {
      await api.post("/watchlist/", { ticker: t, note: newNote.trim() });
      setNewTicker("");
      setNewNote("");
      await loadWatchlist();
    } catch (err) {
      setWlError(extractError(err));
    } finally {
      setAddingWatch(false);
    }
  };

  const indicatorRows = analysis
    ? Object.entries(analysis.indicators).map(([key, val]) => ({ key, val }))
    : [];

  return (
    <div className="grid-2">
      <section className="card">
        <h2 className="card-title">Market analysis</h2>
        <form className="row gap" onSubmit={onAnalyze}>
          <input
            className="grow"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="Ticker e.g. AAPL"
            aria-label="Ticker"
          />
          <button className="btn primary" type="submit" disabled={loading}>
            {loading ? "Analyzing…" : "Analyze"}
          </button>
        </form>

        {error && <div className="alert error">{error}</div>}

        {analysis && (
          <>
            <div className="analysis-head">
              <div>
                <div className="analysis-ticker">{analysis.ticker}</div>
                <div className="muted">via {analysis.provider}</div>
              </div>
              <div className="analysis-price">
                <div className="muted">Latest price</div>
                <div className="price-value">
                  {analysis.latest_price?.toLocaleString(undefined, {
                    maximumFractionDigits: 2,
                  })}
                </div>
              </div>
            </div>

            <div className="chart-frame">
              <LineChart
                values={analysis.closes}
                labels={analysis.dates}
              />
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

        {!analysis && !loading && !error && (
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
          <button className="btn" type="submit" disabled={addingWatch}>
            {addingWatch ? "Adding…" : "Add"}
          </button>
        </form>

        {wlError && <div className="alert error">{wlError}</div>}

        {watchlist.length === 0 ? (
          <p className="muted">No tickers followed yet.</p>
        ) : (
          <ul className="watchlist">
            {watchlist.map((w) => (
              <li key={w.id}>
                <button className="link-ticker" onClick={() => void analyze(w.ticker)}>
                  {w.ticker}
                </button>
                {w.note && <span className="muted"> — {w.note}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
