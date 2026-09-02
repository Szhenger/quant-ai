/**
 * MarketsPanel: an analysis renders the price, the honesty badge and each
 * indicator worded from the field registry; the watchlist adds and removes
 * through the API.
 *
 * @vitest-environment jsdom
 */
import { beforeEach, describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MarketsPanel from "../../../frontend/src/features/markets/MarketsPanel";
import { installFakeApi, paginated, type FakeApi } from "../helpers/fakeApi";
import { catalog, renderWithQuery, signIn, signOut } from "../helpers/render";

const analysis = (ticker: string, synthetic: boolean) => ({
  ticker, provider: synthetic ? "synthetic" : "yfinance", synthetic,
  dates: ["2026-08-28", "2026-08-29", "2026-09-01"], closes: [100, 101.5, 99.25],
  latest_price: 99.25,
  indicators: {
    RSI: { label: "RSI", unit: "", value: 24.3, params: { period: 14 } },
    PRICE: { label: "Price", unit: "$", value: 99.25, params: {} },
  },
});

describe("<MarketsPanel>", () => {
  let wire: FakeApi;

  beforeEach(() => {
    signOut();
    signIn();
    wire = installFakeApi({
      "GET /api/v1/markets/AAPL/analysis/": () => ({ data: analysis("AAPL", false) }),
      "GET /api/v1/markets/ZZZZ/analysis/": () => ({ data: analysis("ZZZZ", true) }),
      "GET /api/v1/indicators/": () => ({ data: catalog }),
      "GET /api/v1/watchlist/": () => ({
        data: paginated([{ id: "w1", ticker: "AAPL", note: "core", refresh_interval_hours: 6,
                           recompute_interval_hours: 24, refreshed_at: null, recomputed_at: null,
                           has_page: false, created_at: "2026-09-01T00:00:00Z" }]),
      }),
      "POST /api/v1/watchlist/": () => ({ status: 201, data: { id: "w2" } }),
      "DELETE /api/v1/watchlist/w1/": () => ({ status: 204 }),
    });
  });

  it("renders the default analysis with each indicator worded from the registry", async () => {
    renderWithQuery(<MarketsPanel />);
    const priceLabel = await screen.findByText("Latest price");
    expect(priceLabel.nextElementSibling).toHaveTextContent("99.25");
    expect(screen.getByText("via yfinance")).toBeInTheDocument();
    expect(screen.queryByText("SYNTHETIC")).not.toBeInTheDocument();
    const rsi = screen.getByRole("row", { name: /RSI/ });
    expect(within(rsi).getByText("24.3")).toBeInTheDocument();
    expect(within(rsi).getByText("oversold")).toBeInTheDocument();
  });

  it("flags synthetic fallback data honestly", async () => {
    const user = userEvent.setup();
    renderWithQuery(<MarketsPanel />);
    await screen.findByText("via yfinance");
    const input = screen.getByLabelText("Ticker");
    await user.clear(input);
    await user.type(input, "zzzz{Enter}");
    expect(await screen.findByText("SYNTHETIC")).toBeInTheDocument();
    expect(screen.getByText(/Simulated data/)).toBeInTheDocument();
    expect(wire.of("GET /api/v1/markets/ZZZZ/analysis/")).toHaveLength(1);
  });

  it("adds to and removes from the watchlist through the API", async () => {
    const user = userEvent.setup();
    renderWithQuery(<MarketsPanel />);
    expect(await screen.findByRole("button", { name: "AAPL" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Watchlist ticker"), "msft");
    await user.type(screen.getByLabelText("Watchlist note"), "mega cap");
    await user.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(wire.of("POST /api/v1/watchlist/")).toHaveLength(1));
    expect(wire.of("POST /api/v1/watchlist/")[0].body).toEqual({ ticker: "MSFT", note: "mega cap" });
    await user.click(screen.getByRole("button", { name: "Remove AAPL from watchlist" }));
    await waitFor(() => expect(wire.of("DELETE /api/v1/watchlist/w1/")).toHaveLength(1));
  });
});
