import { extractError } from "../api/errors";
import {
  useAlertsInfinite,
  useMarkAllRead,
  useMarkRead,
  useUnreadCount,
} from "../api/hooks";
import { useRealtimeStore } from "../realtime/useAlertsSocket";

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export default function AlertsPanel() {
  // The socket lives at the App level and feeds the query cache; this panel is
  // a pure view over that cache plus a "load older pages" cursor walk.
  const alerts = useAlertsInfinite();
  const unread = useUnreadCount();
  const markRead = useMarkRead();
  const markAll = useMarkAllRead();
  const live = useRealtimeStore((s) => s.status);

  const rows = alerts.data?.pages.flatMap((p) => p.results) ?? [];
  const unreadCount = unread.data?.unread ?? 0;

  return (
    <section className="card">
      <div className="card-head">
        <h2 className="card-title">Alerts</h2>
        <div className="row gap">
          {unreadCount > 0 && (
            <button
              className="btn small"
              onClick={() => markAll.mutate()}
              disabled={markAll.isPending}
            >
              Mark all read ({unreadCount})
            </button>
          )}
          <span className={`live-dot ${live === "open" ? "on" : "off"}`}>
            {live === "open" ? "Live" : live === "connecting" ? "Connecting…" : "Offline"}
          </span>
        </div>
      </div>

      {alerts.isError && <div className="alert error">{extractError(alerts.error)}</div>}
      {alerts.isLoading && <p className="muted">Loading alerts…</p>}

      {!alerts.isLoading && rows.length === 0 ? (
        <p className="muted">No alerts yet. They will appear here in real time.</p>
      ) : (
        <>
          <ul className="alert-list">
            {rows.map((a) => (
              <li key={a.id} className={`alert-item ${a.is_read ? "read" : "unread"}`}>
                <div className="alert-top">
                  <span className="alert-ticker">{a.ticker}</span>
                  {a.ai_used && <span className="badge ai">AI</span>}
                  {a.data_synthetic && (
                    <span
                      className="badge synthetic"
                      title="Computed from synthetic fallback data, not real market data"
                    >
                      SYNTHETIC
                    </span>
                  )}
                  {!a.is_read && <span className="badge new">NEW</span>}
                  <span className="alert-time muted">{formatDate(a.created_at)}</span>
                </div>
                <div className="alert-msg">{a.message}</div>
                {a.ai_rationale && (
                  <div className="alert-rationale">
                    <span className="muted">AI rationale: </span>
                    {a.ai_rationale}
                  </div>
                )}
                <div className="alert-actions">
                  {!a.is_read && (
                    <button
                      className="btn small"
                      onClick={() => markRead.mutate(a.id)}
                      disabled={markRead.isPending && markRead.variables === a.id}
                    >
                      Mark read
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>

          {alerts.hasNextPage && (
            <div className="row center">
              <button
                className="btn ghost"
                onClick={() => void alerts.fetchNextPage()}
                disabled={alerts.isFetchingNextPage}
              >
                {alerts.isFetchingNextPage ? "Loading…" : "Load older alerts"}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
