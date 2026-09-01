/**
 * readIndicator mirrors feeder.indicators.read_indicator: the analysis table
 * and the stock page must word a value identically, so the band semantics
 * (ordered, first-match, catch-all last, warm-up text) are pinned here.
 */
import { describe, expect, it } from "vitest";
import { NO_HISTORY_READING, readIndicator } from "../../../frontend/src/api/readings";
import type { Indicator } from "../../../frontend/src/api/types";

const rsi: Indicator = {
  key: "RSI",
  label: "RSI",
  unit: "",
  defaults: { period: 14 },
  default_threshold: 30,
  help: "",
  summary: true,
  readings: [
    { op: "<", at: 30, text: "oversold" },
    { op: ">", at: 70, text: "overbought" },
    { text: "neutral" },
  ],
};

const price: Indicator = { ...rsi, key: "PRICE", label: "Price", summary: false, readings: [] };

describe("readIndicator", () => {
  it("applies bands in order, first match wins", () => {
    expect(readIndicator(rsi, 25)).toBe("oversold");
    expect(readIndicator(rsi, 75)).toBe("overbought");
    expect(readIndicator(rsi, 50)).toBe("neutral");
  });

  it("treats a band boundary exactly like the operator says", () => {
    expect(readIndicator(rsi, 30)).toBe("neutral"); // "<" 30, not "<="
    expect(readIndicator(rsi, 70)).toBe("neutral");
  });

  it("reads the warm-up window and unknown specs honestly", () => {
    expect(readIndicator(rsi, null)).toBe(NO_HISTORY_READING);
    expect(readIndicator(rsi, Number.NaN)).toBe(NO_HISTORY_READING);
    expect(readIndicator(price, 123)).toBe(""); // no bands declared
    expect(readIndicator(undefined, 123)).toBe(""); // catalog not loaded yet
  });
});
