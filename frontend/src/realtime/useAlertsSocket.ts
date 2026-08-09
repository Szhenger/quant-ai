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
import { keys } from "../api/hooks";
import { ReconnectingAlertSocket, SocketStatus } from "./socket";
import { prependAlert, AlertPages } from "./merge";
import type { Alert, UnreadCount } from "../api/types";

interface RealtimeState {
  status: SocketStatus;
  setStatus: (s: SocketStatus) => void;
}

export const useRealtimeStore = create<RealtimeState>((set) => ({
  status: "down",
  setStatus: (status) => set({ status }),
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

    const socket = new ReconnectingAlertSocket({
      // Read the CURRENT token at each connect: refreshed tokens are picked up
      // on reconnect without tearing the socket down at every rotation.
      buildUrl: () => {
        const { workspaceId: ws, access } = useAuthStore.getState();
        if (!ws || !access) return null;
        const base = window.location.origin.replace(/^http/, "ws");
        return `${base}/ws/alerts/${ws}/?token=${encodeURIComponent(access)}`;
      },
      onAlert: (raw) => {
        const alert = raw as Alert;
        const ws = useAuthStore.getState().workspaceId;
        if (!ws) return;
        qc.setQueryData<AlertPages>(keys.alerts(ws), (d) => (d ? prependAlert(d, alert) : d));
        if (!alert.is_read) {
          qc.setQueryData<UnreadCount>(keys.unread(ws), (d) =>
            d ? { unread: d.unread + 1 } : { unread: 1 },
          );
        }
      },
      onStatus: (s) => useRealtimeStore.getState().setStatus(s),
    });

    socket.start();
    return () => socket.stop();
    // `authed` (not the token string) so login/logout resets the socket but
    // routine token refreshes don't.
  }, [workspaceId, authed, qc]);
}
