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
import api, { API_BASE, fetchAllPages } from "./client";
import { relativizeCursor } from "./cursor";
import { useAuthStore } from "../store/auth";
import {
  markAllRead,
  markOneRead,
  markUnread,
  mergeAlerts,
  unreadIds,
} from "../realtime/merge";
import type {
  Alert,
  CursorPage,
  IndicatorCatalog,
  MarketAnalysis,
  ReplayResult,
  StockHistory,
  StockPage,
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
  stockPage: (ws: string, id: string) => [ws, "stock-page", id] as const,
  stockHistory: (ws: string, id: string) => [ws, "stock-history", id] as const,
};

// --- Markets -----------------------------------------------------------------

/** Shared key + fetcher so the hook and the hover-prefetch stay in lockstep. */
function analysisQuery(ws: string, ticker: string, days: number) {
  return {
    queryKey: keys.analysis(ws, ticker, days),
    queryFn: ({ signal }: { signal?: AbortSignal }) =>
      api
        .get<MarketAnalysis>(`/markets/${encodeURIComponent(ticker)}/analysis/`, {
          params: { days },
          signal,
        })
        .then((r) => r.data),
  };
}

export function useAnalysis(ticker: string, days = 180) {
  const ws = useWorkspaceId();
  // Explicit generic: the destructured ({ signal }) queryFn is context-sensitive,
  // so TS would otherwise let keepPreviousData's generic leak into the data type.
  return useQuery<MarketAnalysis>({
    ...analysisQuery(ws, ticker, days),
    enabled: ticker.length > 0,
    // Keep the previous ticker's chart on screen while the next one loads —
    // no flash of empty state on every watchlist click.
    placeholderData: keepPreviousData,
  });
}

/**
 * Latency hiding: warm the analysis cache for a ticker the user is about to
 * click (watchlist hover/focus). prefetchQuery respects staleTime, so repeated
 * hovers inside the fresh window are no-ops, and React Query dedupes it
 * against the real fetch if the click lands mid-flight.
 */
export function usePrefetchAnalysis(days = 180) {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return (ticker: string) => {
    if (!ticker) return;
    void qc.prefetchQuery({ ...analysisQuery(ws, ticker, days), staleTime: 30_000 });
  };
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

// --- Stock page (the compiled per-ticker view) -------------------------------

/** The compiled stock page for a watchlist entry: both measures, detailed +
 *  summarised. The server never compiles on the request path — while a measure
 *  is still being built it answers 202, and this hook polls until it's ready.
 *  Returns `{ ready, page }`: `page` is null until `ready` is true. */
export function useStockPage(watchId: string | null) {
  const ws = useWorkspaceId();
  return useQuery({
    queryKey: keys.stockPage(ws, watchId ?? "none"),
    queryFn: ({ signal }) =>
      api
        .get<StockPage | { status: string; ticker: string }>(
          `/watchlist/${watchId}/page/`,
          { signal },
        )
        .then((r) => ({
          ready: r.status === 200,
          page: r.status === 200 ? (r.data as StockPage) : null,
        })),
    enabled: !!watchId,
    // Poll only while the page is still compiling; stop once it's ready.
    refetchInterval: (query) =>
      query.state.data && !query.state.data.ready ? 2500 : false,
  });
}

export function useRefreshStockPage() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    // Fire-and-forget: the server recomputes on the worker fleet and returns 202.
    // Invalidate so the page query refetches (and then polls) for the fresh data.
    mutationFn: (watchId: string) =>
      api.post(`/watchlist/${watchId}/refresh/`).then((r) => r.data),
    onSuccess: (_data, watchId) => {
      void qc.invalidateQueries({ queryKey: keys.stockPage(ws, watchId) });
      void qc.invalidateQueries({ queryKey: keys.stockHistory(ws, watchId) });
      void qc.invalidateQueries({ queryKey: keys.watchlist(ws) });
    },
  });
}

export function useStockHistory(watchId: string | null) {
  const ws = useWorkspaceId();
  return useQuery({
    queryKey: keys.stockHistory(ws, watchId ?? "none"),
    queryFn: ({ signal }) =>
      api.get<StockHistory>(`/watchlist/${watchId}/history/`, { signal }).then((r) => r.data),
    enabled: !!watchId,
  });
}

/** Update a watchlist entry's cadences (n / m) or note. */
export function useUpdateWatch() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<Pick<WatchedTicker,
      "refresh_interval_hours" | "recompute_interval_hours" | "note">> }) =>
      api.patch<WatchedTicker>(`/watchlist/${id}/`, body).then((r) => r.data),
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

type AlertPages = { pages: CursorPage<Alert>[]; pageParams: unknown[] };

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
