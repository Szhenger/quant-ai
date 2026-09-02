/**
 * StrategiesPanel: the list with cost estimates and account limits, a manual
 * evaluation resolving into human copy (eager and worker-queued), the
 * two-step delete, and the circuit-breaker notice.
 *
 * @vitest-environment jsdom
 */
import { beforeEach, describe, expect, it } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import StrategiesPanel from "../../../frontend/src/features/strategies/StrategiesPanel";
import { useRealtimeStore } from "../../../frontend/src/realtime/store";
import { installFakeApi, paginated, type FakeApi } from "../helpers/fakeApi";
import { catalog, limits, renderWithQuery, signIn, signOut, strategy } from "../helpers/render";

describe("<StrategiesPanel>", () => {
  let wire: FakeApi;

  beforeEach(() => {
    signOut();
    signIn();
    wire = installFakeApi({
      "GET /api/v1/strategies/": () => ({
        data: paginated([
          strategy({ id: "s1", name: "AAPL oversold" }),
          strategy({ id: "s2", name: "MSFT trend", ticker: "MSFT", ai_enabled: false, status: "paused",
                     condition: { type: "group" }, condition_summary: "(SMA_CROSS > 0 AND RSI > 50)",
                     cost_estimate: { evaluations_per_day: 24, ai_calls_per_day_max: 0 } }),
        ]),
      }),
      "GET /api/v1/limits/": () => ({ data: limits }),
      "GET /api/v1/indicators/": () => ({ data: catalog }),
      "POST /api/v1/strategies/s1/evaluate/": () => ({ data: { status: "quant_not_met", value: 41.2 } }),
      "POST /api/v1/strategies/s2/evaluate/": () => ({ status: 202, data: { status: "queued", task_id: "t" } }),
      "DELETE /api/v1/strategies/s1/": () => ({ status: 204 }),
      "GET /api/v1/alerts/": () => ({ data: { next: null, previous: null, results: [] } }),
      "GET /api/v1/alerts/unread-count/": () => ({ data: { unread: 0 } }),
    });
  });

  it("lists strategies with their real firing rule, cost, badges and the account limits", async () => {
    renderWithQuery(<StrategiesPanel />);
    const row1 = (await screen.findByText("AAPL oversold")).closest("tr")!;
    expect(within(row1).getByText("RSI < 30")).toBeInTheDocument();
    expect(within(row1).getByText(/96 evals\/day/)).toBeInTheDocument();
    expect(within(row1).getByText(/≤1 AI\/day/)).toBeInTheDocument();
    expect(within(row1).getByText("AI")).toBeInTheDocument();
    const row2 = screen.getByText("MSFT trend").closest("tr")!;
    expect(within(row2).getByText("(SMA_CROSS > 0 AND RSI > 50)")).toBeInTheDocument();
    expect(within(row2).getByText("composite")).toBeInTheDocument();
    expect(within(row2).getByText("paused")).toBeInTheDocument();
    expect(within(row2).getByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(await screen.findByText(/1 of 50 strategies · AI calls today 3 of 200/)).toBeInTheDocument();
  });

  it("evaluates on demand and words the eager result", async () => {
    const user = userEvent.setup();
    renderWithQuery(<StrategiesPanel />);
    const row = (await screen.findByText("AAPL oversold")).closest("tr")!;
    await user.click(within(row).getByRole("button", { name: "Evaluate" }));
    expect(await within(row).findByText("Condition not met (value 41.20)")).toBeInTheDocument();
    expect(wire.of("POST /api/v1/strategies/s1/evaluate/")).toHaveLength(1);
  });

  it("a queued evaluation resolves when the worker's event lands in the realtime store", async () => {
    const user = userEvent.setup();
    renderWithQuery(<StrategiesPanel />);
    const row = (await screen.findByText("MSFT trend")).closest("tr")!;
    await user.click(within(row).getByRole("button", { name: "Evaluate" }));
    expect(await within(row).findByText(/^Queued/)).toBeInTheDocument();
    act(() => useRealtimeStore.getState().recordEvaluation("s2", { status: "alerted" }));
    expect(await within(row).findByText("Alert fired")).toBeInTheDocument();
  });

  it("deletes only on the second click", async () => {
    const user = userEvent.setup();
    renderWithQuery(<StrategiesPanel />);
    const row = (await screen.findByText("AAPL oversold")).closest("tr")!;
    await user.click(within(row).getByRole("button", { name: "Delete" }));
    expect(within(row).getByRole("button", { name: "Confirm?" })).toBeInTheDocument();
    expect(wire.of("DELETE /api/v1/strategies/s1/")).toHaveLength(0);
    await user.click(within(row).getByRole("button", { name: "Confirm?" }));
    await waitFor(() => expect(wire.of("DELETE /api/v1/strategies/s1/")).toHaveLength(1));
  });

  it("surfaces and dismisses a pushed strategy notice", async () => {
    const user = userEvent.setup();
    renderWithQuery(<StrategiesPanel />);
    await screen.findByText("AAPL oversold");
    act(() => useRealtimeStore.getState().setStrategyNotice("Strategy paused after 5 failures"));
    expect(screen.getByText(/Strategy paused after 5 failures/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText(/Strategy paused/)).not.toBeInTheDocument();
  });
});
