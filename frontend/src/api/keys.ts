/**
 * The React Query key registry. One place, so the feature hooks that own a
 * query and the realtime layer that invalidates it on a workspace event can
 * never disagree about a key — and so realtime/ needs no import from any
 * feature module.
 *
 * Every workspace-scoped key is namespaced by workspace id: switching
 * workspace switches cache namespaces, so one tenant's cached rows can never
 * bleed into another's view.
 */
export const keys = {
  analysis: (ws: string, ticker: string, days: number) => [ws, "analysis", ticker, days] as const,
  watchlist: (ws: string) => [ws, "watchlist"] as const,
  strategies: (ws: string) => [ws, "strategies"] as const,
  catalog: ["catalog"] as const,
  limits: (ws: string) => [ws, "limits"] as const,
  alerts: (ws: string) => [ws, "alerts"] as const,
  unread: (ws: string) => [ws, "unread"] as const,
  replay: (ws: string, id: string, days: number, cooldown: number) =>
    [ws, "replay", id, days, cooldown] as const,
  // Prefix key: invalidating it refetches every open stock page at once.
  stockPages: (ws: string) => [ws, "stock-page"] as const,
  stockPage: (ws: string, id: string) => [ws, "stock-page", id] as const,
  // Prefix key for the continuity trails, same reason as stockPages.
  stockHistories: (ws: string) => [ws, "stock-history"] as const,
  stockHistory: (ws: string, id: string) => [ws, "stock-history", id] as const,
};
