/**
 * Typed server-state hooks. All reads go through React Query so concurrent
 * consumers share one request, unmounted consumers abort theirs, and cached
 * data renders instantly while revalidating in the background.
 *
 * Every workspace-scoped key is namespaced by workspace id: switching
 * workspace can never bleed one tenant's cached rows into another's view.
 */
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import api, { fetchAllPages } from "./client";
import { relativizeCursor } from "./cursor";
import { useAuthStore } from "../store/auth";
import { markAllRead, markOneRead, markUnread, unreadIds } from "../realtime/merge";
import type {
  Alert,
  CursorPage,
  IndicatorCatalog,
  MarketAnalysis,
  ReplayResult,
  Strategy,
  UnreadCount,
  WatchedTicker,
} from "./types";

export function useWorkspaceId(): string {
  return useAuthStore((s) => s.workspaceId) ?? "none";
}

export const keys = {
  analysis: (ws: string, ticker: string, days: number) => [ws, "analysis", ticker, days] as const,
  watchlist: (ws: string) => [ws, "watchlist"] as const,
  strategies: (ws: string) => [ws, "strategies"] as const,
  catalog: ["catalog"] as const,
  alerts: (ws: string) => [ws, "alerts"] as const,
  unread: (ws: string) => [ws, "unread"] as const,
  replay: (ws: string, id: string, days: number, cooldown: number) =>
    [ws, "replay", id, days, cooldown] as const,
};

// --- Markets -----------------------------------------------------------------

export function useAnalysis(ticker: string, days = 180) {
  const ws = useWorkspaceId();
  // Explicit generic: the destructured ({ signal }) queryFn is context-sensitive,
  // so TS would otherwise let keepPreviousData's generic leak into the data type.
  return useQuery<MarketAnalysis>({
    queryKey: keys.analysis(ws, ticker, days),
    queryFn: ({ signal }) =>
      api
        .get<MarketAnalysis>(`/markets/${encodeURIComponent(ticker)}/analysis/`, {
          params: { days },
          signal,
        })
        .then((r) => r.data),
    enabled: ticker.length > 0,
    // Keep the previous ticker's chart on screen while the next one loads —
    // no flash of empty state on every watchlist click.
    placeholderData: keepPreviousData,
  });
}

export function useWatchlist() {
  const ws = useWorkspaceId();
  return useQuery({
    queryKey: keys.watchlist(ws),
    queryFn: () => fetchAllPages<WatchedTicker>("/watchlist/"),
  });
}

export function useAddWatch() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { ticker: string; note: string }) => api.post("/watchlist/", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.watchlist(ws) }),
  });
}

export function useRemoveWatch() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/watchlist/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.watchlist(ws) }),
  });
}

// --- Strategies --------------------------------------------------------------

export function useStrategies() {
  const ws = useWorkspaceId();
  return useQuery({
    queryKey: keys.strategies(ws),
    queryFn: () => fetchAllPages<Strategy>("/strategies/"),
    // Background evaluations mutate status/last_triggered_at server-side;
    // poll gently (only while the tab is visible — React Query pauses hidden tabs).
    refetchInterval: 30_000,
  });
}

export function useIndicatorCatalog() {
  return useQuery({
    queryKey: keys.catalog,
    queryFn: ({ signal }) =>
      api.get<IndicatorCatalog>("/indicators/", { signal }).then((r) => r.data),
    staleTime: Infinity, // static metadata; fetch once per session
  });
}

export function useReplay(strategyId: string | null, days: number, cooldownBars: number) {
  const ws = useWorkspaceId();
  // Explicit generic for the same reason as useAnalysis (keepPreviousData inference).
  return useQuery<ReplayResult>({
    queryKey: keys.replay(ws, strategyId ?? "", days, cooldownBars),
    queryFn: ({ signal }) =>
      api
        .get<ReplayResult>(`/strategies/${strategyId}/replay/`, {
          params: { days, cooldown_bars: cooldownBars },
          signal,
        })
        .then((r) => r.data),
    enabled: strategyId != null,
    staleTime: 5 * 60_000, // deterministic given the same bars; server caches too
    placeholderData: keepPreviousData, // keep the chart while sliding days/cooldown
  });
}

// --- Alerts ------------------------------------------------------------------

export function useAlertsInfinite() {
  const ws = useWorkspaceId();
  return useInfiniteQuery({
    queryKey: keys.alerts(ws),
    queryFn: ({ pageParam, signal }) =>
      api.get<CursorPage<Alert>>(pageParam, { signal }).then((r) => r.data),
    initialPageParam: "/alerts/",
    // DRF's cursor link is absolute and host-based; relativize it so every
    // page stays same-origin (through the dev proxy) — see api/cursor.ts.
    getNextPageParam: (last) => relativizeCursor(last.next),
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

type AlertPages = { pages: CursorPage<Alert>[]; pageParams: unknown[] };

export function useMarkRead() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post(`/alerts/${id}/mark-read/`),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: keys.alerts(ws) });
      await qc.cancelQueries({ queryKey: keys.unread(ws) });
      qc.setQueryData<AlertPages>(keys.alerts(ws), (d) => (d ? markOneRead(d, id) : d));
      qc.setQueryData<UnreadCount>(keys.unread(ws), (d) =>
        d ? { unread: Math.max(0, d.unread - 1) } : d,
      );
    },
    // Rollback by inverse transform on the CURRENT cache, never by snapshot
    // restore: a snapshot would delete socket-delivered alerts that arrived
    // while the POST was in flight (see realtime/merge.ts).
    onError: (_e, id) => {
      qc.setQueryData<AlertPages>(keys.alerts(ws), (d) => (d ? markUnread(d, [id]) : d));
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
      await qc.cancelQueries({ queryKey: keys.alerts(ws) });
      await qc.cancelQueries({ queryKey: keys.unread(ws) });
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

export function useEvaluateStrategy() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: keys.strategies(ws) });
    void qc.invalidateQueries({ queryKey: keys.alerts(ws) });
    void qc.invalidateQueries({ queryKey: keys.unread(ws) });
  };
  return useMutation({
    mutationFn: (id: string) =>
      api.post<{ status: string }>(`/strategies/${id}/evaluate/`).then((r) => r.data),
    onSuccess: (data) => {
      // "queued": the evaluation runs on the worker fleet; refetch again after
      // it has plausibly finished so the row's status/last_* fields catch up
      // without waiting for the 30s strategies poll. (Any fired alert also
      // arrives over the WebSocket regardless.)
      if (data.status === "queued") {
        setTimeout(invalidate, 4_000);
      }
    },
    // An evaluation may have fired an alert and moved strategy timestamps.
    onSettled: invalidate,
  });
}

export function useDeleteStrategy() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/strategies/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.strategies(ws) }),
  });
}

/** PATCH a strategy (edit fields, pause/resume via status). */
export function useUpdateStrategy() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<Strategy> }) =>
      api.patch<Strategy>(`/strategies/${id}/`, patch).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.strategies(ws) }),
  });
}

/** Regenerate a strategy's webhook HMAC secret (receiver must be updated too). */
export function useRotateWebhookSecret() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<Strategy>(`/strategies/${id}/rotate-secret/`).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.strategies(ws) }),
  });
}
