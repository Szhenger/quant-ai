/**
 * Client-side UX journey invariants: realistic sequences of socket frames,
 * refetches, and triage actions over the alert cache. `merge.test.ts` pins
 * each helper in isolation; these tests pin the *sequences* the live UI
 * actually produces — the interleavings that lose data when someone
 * "simplifies" the cache logic in a future PR.
 */
import { describe, expect, it } from "vitest";
import {
  AlertPages,
  markAllRead,
  markOneRead,
  mergeAlerts,
  prependAlert,
  unreadIds,
} from "../../../frontend/src/realtime/merge";
import type { Alert } from "../../../frontend/src/api/types";

function alert(id: string, createdAt: string, is_read = false): Alert {
  return {
    id,
    strategy: null,
    strategy_name: null,
    ticker: "AAPL",
    indicator: "PRICE",
    operator: ">",
    threshold: 0,
    metric_value: 1,
    ai_used: false,
    ai_rationale: null,
    ai_confidence: null,
    message: `[SYNTHETIC DATA] alert ${id}`,
    condition_detail: null,
    data_synthetic: true,
    delivery: null,
    is_read,
    created_at: createdAt,
  };
}

const page = (alerts: Alert[]): AlertPages => ({
  pages: [{ next: null, previous: null, results: alerts }],
  pageParams: ["/alerts/"],
});

describe("refetch racing the socket", () => {
  it("an older REST snapshot never erases a socket-delivered alert", () => {
    // Socket delivered "live" after the REST snapshot was taken.
    const onScreen = [alert("live", "2026-08-14T12:00:10Z"), alert("a", "2026-08-14T12:00:00Z")];
    const fetched = [alert("a", "2026-08-14T12:00:00Z")]; // stale snapshot
    const merged = mergeAlerts(fetched, onScreen);
    expect(merged.map((x) => x.id)).toEqual(["live", "a"]);
  });

  it("fetched rows win read-state for shared ids (server is authoritative)", () => {
    // The user marked "a" read on another device; the refetch carries that.
    const onScreen = [alert("a", "2026-08-14T12:00:00Z", false)];
    const fetched = [alert("a", "2026-08-14T12:00:00Z", true)];
    expect(mergeAlerts(fetched, onScreen)[0]!.is_read).toBe(true);
  });

  it("merge keeps newest-first ordering regardless of input order", () => {
    const merged = mergeAlerts(
      [alert("old", "2026-08-14T11:00:00Z"), alert("new", "2026-08-14T13:00:00Z")],
      [alert("mid", "2026-08-14T12:00:00Z")],
    );
    expect(merged.map((x) => x.id)).toEqual(["new", "mid", "old"]);
  });
});

describe("an alert-storm triage session", () => {
  it("burst → mark-one → mark-all → late socket frame: counts never lie", () => {
    // Three alerts stream in over the socket.
    let cache = page([]);
    cache = prependAlert(cache, alert("a1", "2026-08-14T12:00:01Z"));
    cache = prependAlert(cache, alert("a2", "2026-08-14T12:00:02Z"));
    cache = prependAlert(cache, alert("a3", "2026-08-14T12:00:03Z"));
    expect(unreadIds(cache)).toHaveLength(3);

    // The user triages one, then sweeps the rest.
    cache = markOneRead(cache, "a2");
    expect(unreadIds(cache).sort()).toEqual(["a1", "a3"]);
    cache = markAllRead(cache);
    expect(unreadIds(cache)).toHaveLength(0);

    // A fourth alert lands after the sweep — it must arrive unread, and the
    // unread-only view (the panel's filter) must show exactly it.
    cache = prependAlert(cache, alert("a4", "2026-08-14T12:00:04Z"));
    const rows = cache.pages.flatMap((p) => p.results);
    expect(rows.filter((a) => !a.is_read).map((a) => a.id)).toEqual(["a4"]);
    expect(rows.map((a) => a.id)).toEqual(["a4", "a3", "a2", "a1"]);
  });

  it("a socket redelivery of a triaged alert cannot resurrect its NEW badge", () => {
    // The same alert can arrive twice (socket + refetch race). If it was
    // already marked read, the duplicate frame must not flip it back.
    let cache = page([alert("a1", "2026-08-14T12:00:01Z", true)]);
    cache = prependAlert(cache, alert("a1", "2026-08-14T12:00:01Z", false));
    expect(unreadIds(cache)).toHaveLength(0);
  });
});
