/**
 * The shell: unauthenticated shows the login page; a restorable session is
 * traded back in before the workspace renders; the sidebar badge is live.
 *
 * @vitest-environment jsdom
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../../../frontend/src/app/App";
import { installFakeApi, paginated, type FakeApi } from "../helpers/fakeApi";
import { catalog, renderWithQuery, signIn, signOut, WORKSPACE_ID } from "../helpers/render";

// The shell opens the session socket; keep it inert here (socket.test.ts
// covers the wrapper itself).
class InertWebSocket {
  static OPEN = 1;
  readyState = 0;
  onopen = null; onclose = null; onerror = null; onmessage = null;
  send() {}
  close() {}
}

describe("<App>", () => {
  let wire: FakeApi;

  beforeEach(() => {
    vi.stubGlobal("WebSocket", InertWebSocket);
    signOut();
    localStorage.clear();
    wire = installFakeApi({
      "POST /api/v1/auth/token/refresh/": () => ({ data: { access: "booted", refresh: "rotated" } }),
      "GET /api/v1/workspaces/": () => ({
        data: paginated([{ id: WORKSPACE_ID, name: "Desk", created_at: "2026-01-01T00:00:00Z" }]),
      }),
      "GET /api/v1/alerts/unread-count/": () => ({ data: { unread: 7 } }),
      "GET /api/v1/markets/AAPL/analysis/": () => ({ status: 503, data: { detail: "down" } }),
      "GET /api/v1/indicators/": () => ({ data: catalog }),
      "GET /api/v1/watchlist/": () => ({ data: paginated([]) }),
      "GET /api/v1/strategies/": () => ({ data: paginated([]) }),
      "GET /api/v1/limits/": () => ({ data: { strategy_cap: 0, strategy_count: 0, strategies_remaining: null,
        ai_daily_budget: 200, ai_calls_today: 0, ai_calls_remaining: 200, ai_budget_resets_at: "" } }),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the login page when there is no session", () => {
    renderWithQuery(<App />);
    expect(screen.getByText("AI-powered quantitative research workspace")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(wire.calls).toHaveLength(0);
  });

  it("restores a persisted session before rendering the workspace, with a live badge", async () => {
    signIn({ access: null, workspaces: [] }); // what a page reload leaves: refresh + workspace, no access
    renderWithQuery(<App />);
    expect(screen.getByText("Restoring session…")).toBeInTheDocument();
    expect(await screen.findByText("trader")).toBeInTheDocument();
    expect(wire.of("POST /api/v1/auth/token/refresh/")).toHaveLength(1);
    await waitFor(() => expect(wire.of("GET /api/v1/workspaces/")).toHaveLength(1));
    expect(await screen.findByText("7")).toBeInTheDocument(); // the unread badge on the Alerts tab
  });

  it("switches tabs and logs out", async () => {
    const user = userEvent.setup();
    signIn();
    wire.route("POST /api/v1/auth/logout/", () => ({ status: 205 }));
    renderWithQuery(<App />);
    await user.click(await screen.findByRole("button", { name: /^Strategies/ }));
    expect(await screen.findByText("No strategies yet. Create one below.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Log out" }));
    expect(await screen.findByText("AI-powered quantitative research workspace")).toBeInTheDocument();
  });
});
