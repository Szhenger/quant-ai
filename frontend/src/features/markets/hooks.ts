/**
 * Server-state hooks for the Markets feature: on-demand analysis, the
 * watchlist, and each watched ticker's compiled stock page.
 *
 * All reads go through React Query so concurrent consumers share one request,
 * unmounted consumers abort theirs, and cached data renders instantly while
 * revalidating in the background.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api, { fetchAllPages } from "../../api/client";
import { keys } from "../../api/keys";
import { useWorkspaceId } from "../../session/auth";
import { useSocketLive } from "../../realtime/store";
import type { MarketAnalysis, StockHistory, StockPage, WatchedTicker } from "../../contract/types";

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

export interface StockPageState {
  ready: boolean;
  page: StockPage | null;
}

// Polling fallback. With the workspace socket open, the server pushes
// `stockpage.updated` events and this stands down; it only runs while the
// socket is down, so a broken connection degrades to the old timer behaviour
// instead of to a frozen screen.
const STOCK_PAGE_POLL_MS = 2500;

/** The compiled stock page for a watchlist entry: both measures, detailed +
 *  summarised. The server never compiles on the request path — while a measure
 *  is still being built it answers 202, and this hook polls until it's ready.
 *  Returns `{ ready, page }`: `page` is null until `ready` is true. */
export function useStockPage(watchId: string | null) {
  const ws = useWorkspaceId();
  const live = useSocketLive();
  return useQuery<StockPageState>({
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
    // Socket down: poll while the page is still compiling (202) or while a
    // refresh is in flight behind a served-but-stale page (`refreshing`).
    // Socket open: the compile tasks push `stockpage.updated` instead.
    refetchInterval: (query) => {
      if (live) return false;
      const d = query.state.data;
      if (!d) return false;
      return !d.ready || d.page?.refreshing ? STOCK_PAGE_POLL_MS : false;
    },
  });
}

export function useRefreshStockPage() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    // Fire-and-forget: the server recomputes on the worker fleet and returns 202.
    mutationFn: (watchId: string) =>
      api.post(`/watchlist/${watchId}/refresh/`).then((r) => r.data),
    onSuccess: (_data, watchId) => {
      // Flip the cached page to `refreshing` immediately so the poll starts on
      // this render, not after the invalidation round-trip; the server reports
      // the same flag until the recompile lands, then the poll stops itself.
      qc.setQueryData<StockPageState>(keys.stockPage(ws, watchId), (d) =>
        d?.page ? { ...d, page: { ...d.page, refreshing: true } } : d,
      );
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
