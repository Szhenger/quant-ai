/**
 * AlertsPanel: renders the cursor page, the unread controls, optimistic
 * mark-read with the server confirming, the audit detail toggle, and the
 * live dot bound to the realtime store.
 *
 * @vitest-environment jsdom
 */
import { beforeEach, describe, expect, it } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AlertsPanel from "../../../frontend/src/features/alerts/AlertsPanel";
import { useRealtimeStore } from "../../../frontend/src/realtime/store";
import { cursorPage, installFakeApi, type FakeApi } from "../helpers/fakeApi";
import { alert, renderWithQuery, signIn, signOut } from "../helpers/render";

describe("<AlertsPanel>", () => {
  let wire: FakeApi;

  beforeEach(() => {
    signOut();
    signIn();
    wire = installFakeApi({
      "GET /api/v1/alerts/": () => ({
        data: cursorPage([
          alert({ id: "a1", ticker: "AAPL" }),
          alert({ id: "a2", ticker: "MSFT", is_read: true, ai_used: false, ai_rationale: null, data_synthetic: true }),
        ]),
      }),
      "GET /api/v1/alerts/unread-count/": () => ({ data: { unread: 1 } }),
      "POST /api/v1/alerts/a1/mark-read/": () => ({ data: alert({ id: "a1", is_read: true }) }),
      "POST /api/v1/alerts/mark-all-read/": () => ({ data: { updated: 1 } }),
    });
  });

  it("renders alerts with their badges and the unread count", async () => {
    renderWithQuery(<AlertsPanel />);
    const aapl = (await screen.findByText("AAPL")).closest("li")!;
    expect(within(aapl).getByText("NEW")).toBeInTheDocument();
    expect(within(aapl).getByText("AI")).toBeInTheDocument();
    expect(within(aapl).getByText(/80% confidence/)).toBeInTheDocument();
    const msft = screen.getByText("MSFT").closest("li")!;
    expect(within(msft).getByText("SYNTHETIC")).toBeInTheDocument();
    expect(within(msft).queryByText("NEW")).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Mark all read (1)" })).toBeInTheDocument();
  });

  it("marks one alert read optimistically and confirms with the server", async () => {
    const user = userEvent.setup();
    renderWithQuery(<AlertsPanel />);
    const aapl = (await screen.findByText("AAPL")).closest("li")!;
    await user.click(within(aapl).getByRole("button", { name: "Mark read" }));
    // Optimistic: the NEW badge and the button are gone before the server answers.
    await waitFor(() => expect(within(aapl).queryByText("NEW")).not.toBeInTheDocument());
    await waitFor(() => expect(wire.of("POST /api/v1/alerts/a1/mark-read/")).toHaveLength(1));
    // "Unread only" then hides it.
    await user.click(screen.getByRole("button", { name: "Unread only" }));
    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
    expect(screen.getByText("No unread alerts in the loaded pages.")).toBeInTheDocument();
  });

  it("toggles the audit detail for one alert", async () => {
    const user = userEvent.setup();
    renderWithQuery(<AlertsPanel />);
    const aapl = (await screen.findByText("AAPL")).closest("li")!;
    await user.click(within(aapl).getByRole("button", { name: "Detail" }));
    expect(within(aapl).getByRole("button", { name: "Hide detail" })).toBeInTheDocument();
    expect(within(aapl).getByText(/in_app/)).toBeInTheDocument();
  });

  it("shows the socket state from the realtime store", async () => {
    renderWithQuery(<AlertsPanel />);
    expect(await screen.findByText("Offline")).toBeInTheDocument();
    act(() => useRealtimeStore.getState().setStatus("open"));
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("explains an empty history", async () => {
    wire.route("GET /api/v1/alerts/", () => ({ data: cursorPage([]) }));
    wire.route("GET /api/v1/alerts/unread-count/", () => ({ data: { unread: 0 } }));
    renderWithQuery(<AlertsPanel />);
    expect(await screen.findByText(/No alerts yet/)).toBeInTheDocument();
  });
});
