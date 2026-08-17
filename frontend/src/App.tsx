import { useEffect, useState } from "react";
import { bootstrapAccess } from "./api/client";
import { useAuthStore } from "./store/auth";
import { useUnreadCount } from "./api/hooks";
import { useAlertsSocket } from "./realtime/useAlertsSocket";
import LoginPage from "./pages/LoginPage";
import MarketsPanel from "./components/MarketsPanel";
import StrategiesPanel from "./components/StrategiesPanel";
import AlertsPanel from "./components/AlertsPanel";

type Tab = "markets" | "strategies" | "alerts";

const TABS: { key: Tab; label: string }[] = [
  { key: "markets", label: "Markets" },
  { key: "strategies", label: "Strategies" },
  { key: "alerts", label: "Alerts" },
];

function Workspace() {
  const workspaces = useAuthStore((s) => s.workspaces);
  const workspaceId = useAuthStore((s) => s.workspaceId);
  const setWorkspace = useAuthStore((s) => s.setWorkspace);
  const username = useAuthStore((s) => s.username);
  const logout = useAuthStore((s) => s.logout);

  const [tab, setTab] = useState<Tab>("markets");

  // One socket for the whole session: alerts stream into the query cache on
  // every tab, and the sidebar badge stays live without the Alerts panel mounted.
  useAlertsSocket();
  const { data: unread } = useUnreadCount();
  const unreadCount = unread?.unread ?? 0;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">◆</span> QuantAI
        </div>
        <nav className="nav">
          {TABS.map((t) => (
            <button
              key={t.key}
              className={`nav-item ${tab === t.key ? "active" : ""}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
              {t.key === "alerts" && unreadCount > 0 && (
                <span className="badge new nav-badge">{unreadCount > 99 ? "99+" : unreadCount}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">AI-powered quant research</div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar-title">
            {TABS.find((t) => t.key === tab)?.label}
          </div>
          <div className="topbar-actions">
            {workspaces.length > 1 && (
              <select
                className="ws-select"
                value={workspaceId ?? ""}
                onChange={(e) => setWorkspace(e.target.value)}
              >
                {workspaces.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            )}
            <span className="user-badge">{username}</span>
            <button className="btn ghost" onClick={logout}>
              Log out
            </button>
          </div>
        </header>

        {/* Query keys are namespaced by workspace id, so switching workspace
            reads a different cache namespace; keying the content remounts the
            panels so their local UI state (selected ticker, open replay row)
            resets with it. */}
        <main className="content" key={workspaceId ?? "none"}>
          {tab === "markets" && <MarketsPanel />}
          {tab === "strategies" && <StrategiesPanel />}
          {tab === "alerts" && <AlertsPanel />}
        </main>
      </div>
    </div>
  );
}

export default function App() {
  const access = useAuthStore((s) => s.access);
  const refresh = useAuthStore((s) => s.refresh);
  const workspaces = useAuthStore((s) => s.workspaces);
  const loadWorkspaces = useAuthStore((s) => s.loadWorkspaces);

  // The access token is memory-only (never persisted): after a page load,
  // trade the persisted refresh token back in before deciding between the
  // login page and the workspace, so a reload doesn't flash the login screen.
  const [restoring, setRestoring] = useState(() => refresh != null);
  useEffect(() => {
    if (access || !refresh) {
      setRestoring(false);
      return;
    }
    let cancelled = false;
    void bootstrapAccess().finally(() => {
      if (!cancelled) setRestoring(false);
    });
    return () => {
      cancelled = true;
    };
  }, [access, refresh]);

  // After a page refresh the store rehydrates workspaceId but not the
  // workspaces array — reload it, and RETRY with backoff: one failed load
  // (cold backend, 502) must not wedge the app in a workspace-less state
  // with no path to recovery except a manual reload.
  useEffect(() => {
    if (!access || workspaces.length > 0) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let delay = 2_000;
    const attempt = () => {
      loadWorkspaces().catch(() => {
        if (cancelled) return;
        timer = setTimeout(attempt, delay);
        delay = Math.min(delay * 2, 30_000);
      });
    };
    attempt();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [access, workspaces.length, loadWorkspaces]);

  if (!access) {
    return restoring ? (
      <div className="login-page">
        <p className="muted">Restoring session…</p>
      </div>
    ) : (
      <LoginPage />
    );
  }
  return <Workspace />;
}
