/**
 * Server-state hooks for the Strategies feature: the list, replay, manual
 * evaluation, the account limits shown beside every deploy button, and the
 * create/deploy/update/delete/rotate mutations.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api, { fetchAllPages } from "../../api/client";
import { keys } from "../../api/keys";
import { useWorkspaceId } from "../../session/auth";
import { useSocketLive } from "../../realtime/store";
import type { GraphDeployRequest, Limits, ReplayResult, Strategy } from "../../contract/types";

// Polling fallback. With the workspace socket open, the server pushes
// `strategy.evaluated` events and this stands down; it only runs while the
// socket is down, so a broken connection degrades to the old timer behaviour
// instead of to a frozen screen.
const STRATEGIES_POLL_MS = 30_000;

// --- Strategies --------------------------------------------------------------

export function useStrategies() {
  const ws = useWorkspaceId();
  const live = useSocketLive();
  return useQuery({
    queryKey: keys.strategies(ws),
    queryFn: () => fetchAllPages<Strategy>("/strategies/"),
    // Background evaluations mutate status/last_* server-side and push a
    // `strategy.evaluated` event; the gentle poll is only the socket-down fallback.
    refetchInterval: live ? false : STRATEGIES_POLL_MS,
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
    // "queued": the evaluation runs on the worker fleet and its outcome
    // arrives as a `strategy.evaluated` event (which invalidates again). Any
    // other status ran eagerly, so the row and alerts may already have moved.
    onSettled: invalidate,
  });
}

export function useDeleteStrategy() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/strategies/${id}/`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.strategies(ws) });
      void qc.invalidateQueries({ queryKey: keys.limits(ws) });
    },
  });
}

/** The account guards (strategy cap, daily AI budget) and their current usage. */
export function useLimits() {
  const ws = useWorkspaceId();
  return useQuery({
    queryKey: keys.limits(ws),
    queryFn: ({ signal }) => api.get<Limits>("/limits/", { signal }).then((r) => r.data),
  });
}

/** POST a strategy authored in the plain form (simple mode: flat fields). */
export function useCreateStrategy() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<Strategy>) =>
      api.post<Strategy>("/strategies/", body).then((r) => r.data),
    // Whether it succeeded or hit the cap, the count shown next to the
    // button must be the server's.
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: keys.strategies(ws) });
      void qc.invalidateQueries({ queryKey: keys.limits(ws) });
    },
  });
}

/** POST a React Flow graph; the server compiles it into a composite strategy. */
export function useDeployGraph() {
  const ws = useWorkspaceId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: GraphDeployRequest) =>
      api.post<Strategy>("/strategies/deploy-graph/", body).then((r) => r.data),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: keys.strategies(ws) });
      void qc.invalidateQueries({ queryKey: keys.limits(ws) });
    },
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
