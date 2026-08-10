import { create } from "zustand";
import { persist } from "zustand/middleware";
import axios from "axios";
import api, { API_BASE } from "../api/client";
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
      partialize: (state) => ({
        access: state.access,
        refresh: state.refresh,
        workspaceId: state.workspaceId,
        username: state.username,
      }),
    },
  ),
);
