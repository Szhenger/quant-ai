import { useState } from "react";
import { useAuthStore } from "./store/auth";
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

export default function App() {
  const access = useAuthStore((s) => s.access);
  const username = useAuthStore((s) => s.username);
  const workspaces = useAuthStore((s) => s.workspaces);
  const workspaceId = useAuthStore((s) => s.workspaceId);
  const setWorkspace = useAuthStore((s) => s.setWorkspace);
  const logout = useAuthStore((s) => s.logout);

  const [tab, setTab] = useState<Tab>("markets");

  if (!access) {
    return <LoginPage />;
  }

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

        <main className="content">
          {tab === "markets" && <MarketsPanel />}
          {tab === "strategies" && <StrategiesPanel />}
          {tab === "alerts" && <AlertsPanel />}
        </main>
      </div>
    </div>
  );
}
