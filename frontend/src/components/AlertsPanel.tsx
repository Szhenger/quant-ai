import { useEffect, useState } from "react";
import api, { WS_BASE } from "../api/client";
import { extractError } from "../api/errors";
import { useAuthStore } from "../store/auth";
import { ReconnectingAlertSocket, SocketStatus } from "../realtime/socket";
import { mergeAlerts } from "../realtime/merge";
import type { Alert, Paginated } from "../api/types";

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

const STATUS_LABEL: Record<SocketStatus, string> = {
  open: "Live",
  connecting: "Connecting…",
  down: "Offline",
};

export default function AlertsPanel() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<SocketStatus>("down");
  const [nextUrl, setNextUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await api.get<Paginated<Alert>>("/alerts/");
        // Merge, don't replace: an alert that arrived over the socket while
        // this (older) snapshot was in flight must survive the load.
        if (!cancelled) {
          setAlerts((prev) => mergeAlerts(res.data.results, prev));
          setNextUrl(res.data.next);
        }
      } catch (err) {
        if (!cancelled) setError(extractError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();

    const { workspaceId } = useAuthStore.getState();
    if (!workspaceId) {
      return () => {
        cancelled = true;
      };
    }

    let wasOpen = false;
    const socket = new ReconnectingAlertSocket({
      // Read the token at each (re)connect so a rotated access token is picked
      // up without tearing the socket down.
      buildUrl: () => {
        const { access } = useAuthStore.getState();
        if (!access) return null;
        return `${WS_BASE}/ws/alerts/${workspaceId}/?token=${encodeURIComponent(access)}`;
      },
      onAlert: (raw) => {
        const incoming = raw as Alert;
        setAlerts((prev) =>
          prev.some((a) => a.id === incoming.id) ? prev : [incoming, ...prev],
        );
      },
      onStatus: (s) => {
        if (cancelled) return;
        setStatus(s);
        // On REconnect, refetch to pick up anything fired while offline
        // (the merge keeps whatever the socket already delivered).
        if (s === "open" && wasOpen) void load();
        if (s === "open") wasOpen = true;
      },
    });
    socket.start();

    return () => {
      cancelled = true;
      socket.stop();
    };
  }, []);

  const markRead = async (id: string) => {
    try {
      await api.post(`/alerts/${id}/mark-read/`);
      setAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, is_read: true } : a)));
    } catch (err) {
      setError(extractError(err));
    }
  };

  const markAllRead = async () => {
    try {
      await api.post("/alerts/mark-all-read/");
      setAlerts((prev) => prev.map((a) => (a.is_read ? a : { ...a, is_read: true })));
    } catch (err) {
      setError(extractError(err));
    }
  };

  // `next` is an absolute URL from the pagination envelope; the merge dedupes
  // any rows that shifted between pages as new alerts arrived.
  const loadMore = async () => {
    if (!nextUrl) return;
    try {
      const res = await api.get<Paginated<Alert>>(nextUrl);
      setAlerts((prev) => mergeAlerts(res.data.results, prev));
      setNextUrl(res.data.next);
    } catch (err) {
      setError(extractError(err));
    }
  };

  const hasUnread = alerts.some((a) => !a.is_read);

  return (
    <section className="card">
      <div className="card-head">
        <h2 className="card-title">Alerts</h2>
        <div className="topbar-actions">
          {hasUnread && (
            <button className="btn small" onClick={() => void markAllRead()}>
              Mark all read
            </button>
          )}
          <span className={`live-dot ${status === "open" ? "on" : "off"}`}>
            {STATUS_LABEL[status]}
          </span>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {loading && <p className="muted">Loading alerts…</p>}

      {!loading && alerts.length === 0 ? (
        <p className="muted">No alerts yet. They will appear here in real time.</p>
      ) : (
        <ul className="alert-list">
          {alerts.map((a) => (
            <li key={a.id} className={`alert-item ${a.is_read ? "read" : "unread"}`}>
              <div className="alert-top">
                <span className="alert-ticker">{a.ticker}</span>
                {a.ai_used && <span className="badge ai">AI</span>}
                {a.data_synthetic && (
                  <span className="badge synthetic" title="Computed from synthetic fallback data, not real market data">
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
                  <button className="btn small" onClick={() => void markRead(a.id)}>
                    Mark read
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {nextUrl && !loading && (
        <button className="btn ghost" onClick={() => void loadMore()}>
          Load older alerts
        </button>
      )}
    </section>
  );
}
