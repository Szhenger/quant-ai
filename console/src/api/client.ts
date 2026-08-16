import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";
import { useAuthStore } from "../store/auth";
import type { Paginated } from "./types";

// Absolute bases for split-origin deployments (static frontend + API service).
// Default to same-origin relative paths, which the Vite dev proxy serves.
export const API_BASE = import.meta.env.VITE_API_BASE || "/api/v1";
export const WS_BASE =
  import.meta.env.VITE_WS_BASE || window.location.origin.replace(/^http/, "ws");

const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const { access, workspaceId } = useAuthStore.getState();
  if (access) {
    config.headers.set("Authorization", `Bearer ${access}`);
  }
  if (workspaceId) {
    config.headers.set("X-Workspace-ID", workspaceId);
  }
  return config;
});

// Single-flight token refresh so parallel 401s don't each hit the endpoint.
let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const { refresh } = useAuthStore.getState();
  if (!refresh) return null;
  try {
    // Use a bare axios call so we don't recurse through these interceptors.
    // The backend rotates refresh tokens and blacklists the submitted one, so
    // the NEW refresh token must be persisted too — keeping the old one means
    // the next refresh fails and the user is force-logged-out.
    const res = await axios.post<{ access: string; refresh?: string }>(
      `${API_BASE}/auth/token/refresh/`,
      { refresh },
    );
    const access = res.data.access;
    useAuthStore.getState().setTokens(access, res.data.refresh ?? refresh);
    return access;
  } catch {
    return null;
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as
      | (InternalAxiosRequestConfig & { _retry?: boolean })
      | undefined;

    if (error.response?.status === 401 && original && !original._retry) {
      original._retry = true;
      if (!refreshPromise) {
        refreshPromise = refreshAccessToken().finally(() => {
          refreshPromise = null;
        });
      }
      const newAccess = await refreshPromise;
      if (newAccess) {
        original.headers.set("Authorization", `Bearer ${newAccess}`);
        return api(original);
      }
      // Refresh failed: clear session. App re-renders to the login page.
      useAuthStore.getState().logout();
    }
    return Promise.reject(error);
  },
);

/**
 * Fetch every page of a LimitOffset-paginated endpoint, so lists are never
 * silently truncated at the server page size.
 *
 * The first response carries `count`, so every remaining page's offset is
 * known up front — fetch them CONCURRENTLY (one Promise.all) instead of
 * walking `next` links one round-trip at a time: N pages cost ~2 RTTs, not N.
 * `cap` bounds the total page requests (cap × server page size items) as a
 * runaway guard. Offset pages can shift under concurrent writes exactly as
 * they could during the sequential walk; React Query's background refetches
 * reconcile either way.
 */
export async function fetchAllPages<T>(path: string, cap = 10): Promise<T[]> {
  const first = await api.get<Paginated<T>>(path);
  const { results, count, next } = first.data;
  const pageSize = results.length;
  if (!next || pageSize === 0) return results;

  const offsets: number[] = [];
  for (let o = pageSize; o < count && offsets.length < cap - 1; o += pageSize) {
    offsets.push(o);
  }
  const rest = await Promise.all(
    offsets.map((offset) =>
      api
        .get<Paginated<T>>(path, { params: { limit: pageSize, offset } })
        .then((r) => r.data.results),
    ),
  );
  return results.concat(...rest);
}

export default api;
