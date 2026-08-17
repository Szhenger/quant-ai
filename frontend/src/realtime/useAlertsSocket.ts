/**
 * App-level realtime wiring: one socket per session, alive on every tab.
 *
 * Incoming alerts land directly in the React Query cache (prepend + unread
 * bump), so whichever panel is mounted re-renders from cache — the socket
 * doesn't care what's on screen, and no panel owns the connection.
 */
import { useEffect } from "react";
import { create } from "zustand";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "../store/auth";
import { WS_BASE } from "../api/client";
import { keys } from "../api/hooks";
import { ReconnectingAlertSocket, SocketStatus } from "./socket";
import { prependAlert, AlertPages } from "./merge";
import type { Alert, UnreadCount } from "../api/types";

interface RealtimeState {
  status: SocketStatus;
  setStatus: (s: SocketStatus) => void;
  // Latest strategy lifecycle notice pushed by the server (circuit breaker
  // tripped, etc.) — rendered as a dismissible banner in the strategies panel.
  strategyNotice: string | null;
  setStrategyNotice: (message: string | null) => void;
}

export const useRealtimeStore = create<RealtimeState>((set) => ({
  status: "down",
  setStatus: (status) => set({ status }),
  strategyNotice: null,
  setStrategyNotice: (strategyNotice) => set({ strategyNotice }),
}));

export function useAlertsSocket(): void {
  const workspaceId = useAuthStore((s) => s.workspaceId);
  const authed = useAuthStore((s) => s.access != null);
  const qc = useQueryClient();

  useEffect(() => {
    if (!workspaceId || !authed) {
      useRealtimeStore.getState().setStatus("down");
      return;
    }

    // Whether THIS effect's socket has completed a connect before — true from
    // the first open, so any later open is a reconnect after an outage.
    let hadOpened = false;

    const socket = new ReconnectingAlertSocket({
      // Token: read the CURRENT value at each connect, so refreshed tokens are
      // picked up on reconnect without tearing the socket down at every
      // rotation. Workspace: pinned to THIS effect's value — a reconnect
      // firing mid-switch must not attach this instance to another tenant's
      // channel (the effect re-runs to build the new workspace's socket).
      buildUrl: () => {
        const { access } = useAuthStore.getState();
        if (!access) return null;
        // WS_BASE, not window.location.origin: in split-origin deployments the
        // frontend is a static site and the socket must dial the API service
        // (VITE_WS_BASE); same-origin remains the dev default. The token is
        // NOT in this URL — it rides in the subprotocol header below, where
        // access logs can't see it.
        return `${WS_BASE}/ws/alerts/${workspaceId}/`;
      },
      buildProtocols: () => {
        const { access } = useAuthStore.getState();
        // The server accepts "quantai.v1" and reads the bearer token from the
        // second offered subprotocol (see backend/engine/ws_auth.py).
        return access ? ["quantai.v1", `quantai.token.${access}`] : undefined;
      },
      onAlert: (raw) => {
        const alert = raw as Alert;
        // Key by THIS effect's workspace — the one the socket is subscribed
        // to — never the store's current value: during an A -> B switch a
        // frame can arrive after the store flips but before this effect's
        // cleanup closes A's socket, and reading the store then would write
        // A's alert into B's cache namespace.
        qc.setQueryData<AlertPages>(keys.alerts(workspaceId), (d) =>
          d ? prependAlert(d, alert) : d,
        );
        if (!alert.is_read) {
          qc.setQueryData<UnreadCount>(keys.unread(workspaceId), (d) =>
            d ? { unread: d.unread + 1 } : { unread: 1 },
          );
        }
      },
      onStrategyStatus: (raw) => {
        const payload = raw as { message?: unknown };
        if (typeof payload.message === "string") {
          useRealtimeStore.getState().setStrategyNotice(payload.message);
        }
        // The pushed strategy changed server-side (e.g. status -> failed).
        void qc.invalidateQueries({ queryKey: keys.strategies(workspaceId) });
      },
      onStatus: (s) => {
        // Missed-alert catch-up: alerts fired while the socket was down were
        // group-sent to nobody. On every RE-connect (not the initial open),
        // refetch the list — the id-dedupe in realtime/merge makes replays of
        // frames that did arrive harmless.
        if (s === "open" && hadOpened) {
          void qc.invalidateQueries({ queryKey: keys.alerts(workspaceId) });
          void qc.invalidateQueries({ queryKey: keys.unread(workspaceId) });
        }
        if (s === "open") hadOpened = true;
        useRealtimeStore.getState().setStatus(s);
      },
    });

    socket.start();
    return () => socket.stop();
    // `authed` (not the token string) so login/logout resets the socket but
    // routine token refreshes don't.
  }, [workspaceId, authed, qc]);
}
