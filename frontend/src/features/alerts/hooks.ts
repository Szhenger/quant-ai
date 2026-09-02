/**
 * Server-state hooks for the Alerts feature: the infinite cursor-paged
 * history, the unread badge count, and the optimistic mark-read mutations
 * (rollback by inverse transform — see realtime/merge.ts for why).
 */
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../../api/client";
import { keys } from "../../api/keys";
import { API_BASE } from "../../config";
import { relativizeCursor } from "../../contract/cursor";
import { useWorkspaceId } from "../../session/auth";
import {
  markAllRead,
  markOneRead,
  markUnread,
  mergeAlerts,
  unreadIds,
  type AlertPages,
} from "../../realtime/merge";
import type { Alert, CursorPage, UnreadCount } from "../../contract/types";

// --- Alerts ------------------------------------------------------------------

export function useAlertsInfinite() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return useInfiniteQuery({
    queryKey: keys.alerts(ws),
    queryFn: async ({ pageParam, signal }) => {
      const page = (await api.get<CursorPage<Alert>>(pageParam, { signal })).data;
      if (pageParam !== "/alerts/") return page;
      // First page: MERGE with the cached first page instead of replacing it.
      // A socket-delivered alert prepended while this fetch was in flight
      // would otherwise be erased by a response serialized before the alert
      // existed — the lost-update race realtime/merge.ts exists to prevent.
      // (Fetched rows win for shared ids; render-side flattenPages dedupes
      // any row that momentarily spans a page boundary.)
      const cached = qc.getQueryData<AlertPages>(keys.alerts(ws));
      const current = cached?.pages[0]?.results ?? [];
      return { ...page, results: mergeAlerts(page.results, current) };
    },
    initialPageParam: "/alerts/",
    // DRF's cursor link is absolute and host-based; relativize it (against the
    // configured API base) so every page stays same-origin — see api/cursor.ts.
    getNextPageParam: (last) => relativizeCursor(last.next, API_BASE),
  });
}

export function useUnreadCount() {
  const ws = useWorkspaceId();
  return useQuery({
    queryKey: keys.unread(ws),
    queryFn: ({ signal }) =>
      api.get<UnreadCount>("/alerts/unread-count/", { signal }).then((r) => r.data),
    // The WebSocket bumps this optimistically; this poll is the fallback that
    // reconciles after missed frames or reconnects.
    refetchInterval: 60_000,
  });
}

export function useMarkRead() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post(`/alerts/${id}/mark-read/`),
    onMutate: async (id) => {
      // Independent cancellations — run them concurrently, not back-to-back.
      await Promise.all([
        qc.cancelQueries({ queryKey: keys.alerts(ws) }),
        qc.cancelQueries({ queryKey: keys.unread(ws) }),
      ]);
      // Guard against double-marking (rapid clicks, two tabs): only an alert
      // that is actually unread moves the badge, and only that transition is
      // rolled back on error — never an already-read row flipped to unread.
      const cached = qc.getQueryData<AlertPages>(keys.alerts(ws));
      const target = cached?.pages
        .flatMap((p) => p.results)
        .find((a) => a.id === id);
      const wasUnread = target ? !target.is_read : true;
      qc.setQueryData<AlertPages>(keys.alerts(ws), (d) => (d ? markOneRead(d, id) : d));
      if (wasUnread) {
        qc.setQueryData<UnreadCount>(keys.unread(ws), (d) =>
          d ? { unread: Math.max(0, d.unread - 1) } : d,
        );
      }
      return { wasUnread };
    },
    // Rollback by inverse transform on the CURRENT cache, never by snapshot
    // restore: a snapshot would delete socket-delivered alerts that arrived
    // while the POST was in flight (see realtime/merge.ts).
    onError: (_e, id, ctx) => {
      if (ctx?.wasUnread) {
        qc.setQueryData<AlertPages>(keys.alerts(ws), (d) => (d ? markUnread(d, [id]) : d));
      }
    },
    // Authoritative reconciliation for the counter either way.
    onSettled: () => qc.invalidateQueries({ queryKey: keys.unread(ws) }),
  });
}

export function useMarkAllRead() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post("/alerts/mark-all-read/"),
    onMutate: async () => {
      await Promise.all([
        qc.cancelQueries({ queryKey: keys.alerts(ws) }),
        qc.cancelQueries({ queryKey: keys.unread(ws) }),
      ]);
      const prev = qc.getQueryData<AlertPages>(keys.alerts(ws));
      // Snapshot only the ids we are about to flip — the rollback un-flips
      // exactly those on whatever the cache holds by then.
      const flipped = prev ? unreadIds(prev) : [];
      qc.setQueryData<AlertPages>(keys.alerts(ws), (d) => (d ? markAllRead(d) : d));
      qc.setQueryData<UnreadCount>(keys.unread(ws), { unread: 0 });
      return { flipped };
    },
    onError: (_e, _v, ctx) => {
      const flipped = ctx?.flipped ?? [];
      if (flipped.length > 0) {
        qc.setQueryData<AlertPages>(keys.alerts(ws), (d) => (d ? markUnread(d, flipped) : d));
      }
    },
    onSettled: () => qc.invalidateQueries({ queryKey: keys.unread(ws) }),
  });
}
