import { useEffect, useRef, useState } from "react";
import api from "../api/client";
import { extractError } from "../api/errors";
import { useAuthStore } from "../store/auth";
import type { Alert, Paginated } from "../api/types";

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export default function AlertsPanel() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);

  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await api.get<Paginated<Alert>>("/alerts/");
        if (!cancelled) setAlerts(res.data.results);
      } catch (err) {
        if (!cancelled) setError(extractError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();

    const { workspaceId, access } = useAuthStore.getState();
    if (workspaceId && access) {
      const wsBase = window.location.origin.replace("http", "ws");
      const url = `${wsBase}/ws/alerts/${workspaceId}/?token=${access}`;
      const socket = new WebSocket(url);
      socketRef.current = socket;

      socket.onopen = () => setLive(true);
      socket.onclose = () => setLive(false);
      socket.onerror = () => setLive(false);
      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as { type: string; alert?: Alert };
          if (data.type === "alert" && data.alert) {
            const incoming = data.alert;
            setAlerts((prev) =>
              prev.some((a) => a.id === incoming.id) ? prev : [incoming, ...prev],
            );
          }
        } catch {
          // Ignore malformed frames.
        }
      };
    }

    return () => {
      cancelled = true;
      const socket = socketRef.current;
      if (socket) {
        socket.onopen = null;
        socket.onclose = null;
        socket.onerror = null;
        socket.onmessage = null;
        socket.close();
        socketRef.current = null;
      }
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

  return (
    <section className="card">
      <div className="card-head">
        <h2 className="card-title">Alerts</h2>
        <span className={`live-dot ${live ? "on" : "off"}`}>
          {live ? "Live" : "Offline"}
        </span>
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
    </section>
  );
}
