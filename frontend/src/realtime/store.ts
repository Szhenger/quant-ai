/**
 * Client-side realtime state, kept apart from the socket wiring so feature
 * hooks can read "is the socket live?" without depending on the socket itself.
 */
import { create } from "zustand";
import type { EvaluateResult } from "../contract/types";
import type { SocketStatus } from "./socket";

export interface RealtimeState {
  status: SocketStatus;
  setStatus: (s: SocketStatus) => void;
  // Latest strategy lifecycle notice pushed by the server (circuit breaker
  // tripped, etc.) — rendered as a dismissible banner in the strategies panel.
  strategyNotice: string | null;
  setStrategyNotice: (message: string | null) => void;
  // Most recent `strategy.evaluated` event per strategy id: the outcome of a
  // background evaluation, so a "Queued" cell can resolve into the real result.
  evaluations: Record<string, EvaluateResult>;
  recordEvaluation: (strategyId: string, result: EvaluateResult) => void;
}

export const useRealtimeStore = create<RealtimeState>((set) => ({
  status: "down",
  setStatus: (status) => set({ status }),
  strategyNotice: null,
  setStrategyNotice: (strategyNotice) => set({ strategyNotice }),
  evaluations: {},
  recordEvaluation: (strategyId, result) =>
    set((s) => ({ evaluations: { ...s.evaluations, [strategyId]: result } })),
}));

/** True while the workspace socket is open — the signal that polling fallbacks can stand down. */
export function useSocketLive(): boolean {
  return useRealtimeStore((s) => s.status === "open");
}
