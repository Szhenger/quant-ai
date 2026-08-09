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
      // Token: read the CURRENT value at each connect, so refreshed tokens are
      // picked up on reconnect without tearing the socket down at every
      // rotation. Workspace: pinned to THIS effect's value — a reconnect
      // firing mid-switch must not attach this instance to another tenant's
      // channel (the effect re-runs to build the new workspace's socket).
      buildUrl: () => {
        const { access } = useAuthStore.getState();
        if (!access) return null;
        const base = window.location.origin.replace(/^http/, "ws");
        return `${base}/ws/alerts/${workspaceId}/?token=${encodeURIComponent(access)}`;
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
      onStatus: (s) => useRealtimeStore.getState().setStatus(s),
    });

    socket.start();
    return () => socket.stop();
    // `authed` (not the token string) so login/logout resets the socket but
    // routine token refreshes don't.
  }, [workspaceId, authed, qc]);
}
