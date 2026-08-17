import { create } from "zustand";
import { persist } from "zustand/middleware";
import axios from "axios";
import api, { API_BASE } from "../api/client";
import { queryClient } from "../queryClient";
import type { AuthTokens, Paginated, Workspace } from "../api/types";

interface AuthState {
  access: string | null;
  refresh: string | null;
  workspaceId: string | null;
  username: string | null;
  workspaces: Workspace[];
  register: (username: string, email: string, password: string) => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  setWorkspace: (id: string) => void;
  setTokens: (access: string, refresh: string) => void;
  loadWorkspaces: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      access: null,
      refresh: null,
      workspaceId: null,
      username: null,
      workspaces: [],

      register: async (username, email, password) => {
        // Bare axios: registration needs no auth header and no workspace scope.
        await axios.post(`${API_BASE}/auth/register/`, { username, email, password });
        await get().login(username, password);
      },

      login: async (username, password) => {
        const { data } = await axios.post<AuthTokens>(`${API_BASE}/auth/token/`, {
          username,
          password,
        });
        set({ access: data.access, refresh: data.refresh, username });
        await get().loadWorkspaces();
      },

      loadWorkspaces: async () => {
        const res = await api.get<Paginated<Workspace>>("/workspaces/");
        const results = res.data.results;
        const current = get().workspaceId;
        const stillValid = current && results.some((w) => w.id === current);
        set({
          workspaces: results,
          workspaceId: stillValid ? current : results[0]?.id ?? null,
        });
      },

      logout: () => {
        // Revoke the session server-side: blacklist the refresh token so it
        // stops working everywhere, not just in this browser's storage.
        // Bare axios, not the api client: its interceptors read the auth store
        // asynchronously, and we clear that store synchronously below — the
        // captured token keeps this request valid regardless of ordering.
        // Best-effort fire-and-forget — local logout must never be blocked
        // by a network failure.
        const { refresh } = get();
        if (refresh) {
          void axios
            .post(`${API_BASE}/auth/logout/`, { refresh })
            .catch(() => undefined);
        }
        set({
          access: null,
          refresh: null,
          workspaceId: null,
          username: null,
          workspaces: [],
        });
        // Drop every cached server response: the next user on this browser
        // must never see the previous session's data flash from cache.
        queryClient.clear();
      },

      setWorkspace: (id) => set({ workspaceId: id }),

      setTokens: (access, refresh) => set({ access, refresh }),
    }),
    {
      name: "quantai-auth",
      // The ACCESS token is deliberately not persisted: it lives in memory
      // only and is traded back in from the refresh token on boot (see
      // bootstrapAccess in api/client.ts). That keeps the short-lived bearer
      // out of localStorage entirely; the refresh token remains there as the
      // session anchor — rotation + server-side blacklisting bound its blast
      // radius, and moving it to an httpOnly cookie is the tracked follow-up.
      partialize: (state) => ({
        refresh: state.refresh,
        workspaceId: state.workspaceId,
        username: state.username,
      }),
    },
  ),
);

// Cross-tab session sync: refresh-token ROTATION in one tab blacklists the
// token every other tab is holding — without this listener, another tab's
// next refresh fails and force-logs it out. Rehydrating on the storage event
// keeps all tabs on the current token pair, and a logout elsewhere clears
// this tab's refresh token too (its in-memory access then expires naturally).
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key === "quantai-auth") {
      void useAuthStore.persist.rehydrate();
    }
  });
}
