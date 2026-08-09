import { describe, expect, it } from "vitest";
import { AlertPages, markAllRead, markOneRead, prependAlert } from "./merge";
import type { Alert } from "../api/types";

function alert(id: string, is_read = false): Alert {
  return {
    id,
    strategy: null,
    strategy_name: null,
    ticker: "AAPL",
    indicator: "Z_SCORE",
    operator: "<",
    threshold: -2,
    metric_value: -2.5,
    ai_used: false,
    ai_rationale: null,
    message: `alert ${id}`,
    condition_detail: null,
    data_synthetic: false,
    delivery: null,
    is_read,
    created_at: "2026-08-09T00:00:00Z",
  };
}

function pages(...ids: string[][]): AlertPages {
  return {
    pages: ids.map((page) => ({ next: null, previous: null, results: page.map((i) => alert(i)) })),
    pageParams: ids.map((_, i) => i),
  };
}

describe("prependAlert", () => {
  it("prepends a new alert to the first page", () => {
    const out = prependAlert(pages(["b", "c"]), alert("a"));
    expect(out.pages[0]!.results.map((a) => a.id)).toEqual(["a", "b", "c"]);
  });

  it("dedupes when the socket and a refetch race on the same alert", () => {
    const data = pages(["a", "b"]);
    const out = prependAlert(data, alert("a"));
    expect(out).toBe(data); // untouched — no duplicate render
  });

  it("dedupes against alerts already on deeper pages", () => {
    const data = pages(["a", "b"], ["c", "d"]);
    const out = prependAlert(data, alert("d"));
    expect(out).toBe(data);
  });

  it("handles an empty cache (no pages yet)", () => {
    const out = prependAlert({ pages: [], pageParams: [] }, alert("a"));
    expect(out.pages[0]!.results.map((a) => a.id)).toEqual(["a"]);
  });

  it("does not mutate the input (React Query requires new references)", () => {
    const data = pages(["b"]);
    const out = prependAlert(data, alert("a"));
    expect(data.pages[0]!.results).toHaveLength(1);
    expect(out.pages[0]!.results).toHaveLength(2);
    expect(out).not.toBe(data);
  });
});

describe("read-state transitions", () => {
  it("markOneRead flips exactly one alert across pages", () => {
    const out = markOneRead(pages(["a", "b"], ["c"]), "c");
    expect(out.pages[0]!.results.every((a) => !a.is_read)).toBe(true);
    expect(out.pages[1]!.results[0]!.is_read).toBe(true);
  });

  it("markAllRead flips every page", () => {
    const out = markAllRead(pages(["a", "b"], ["c"]));
    for (const page of out.pages) {
      expect(page.results.every((a) => a.is_read)).toBe(true);
    }
  });
});
