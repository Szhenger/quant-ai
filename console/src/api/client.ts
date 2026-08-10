import axios, { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from "axios";
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
 * Follow a paginated endpoint's `next` links until exhausted, so lists are
 * never silently truncated at the server page size. `cap` bounds the walk
 * (cap × 50 items) as a runaway guard; `next` is an absolute URL, which axios
 * uses as-is (the auth/workspace interceptors still apply).
 */
export async function fetchAllPages<T>(path: string, cap = 10): Promise<T[]> {
  const out: T[] = [];
  let url: string | null = path;
  for (let page = 0; url && page < cap; page++) {
    const res: AxiosResponse<Paginated<T>> = await api.get<Paginated<T>>(url);
    out.push(...res.data.results);
    url = res.data.next;
  }
  return out;
}

export default api;
