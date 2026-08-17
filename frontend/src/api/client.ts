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
  } catch (err) {
    // Only the refresh endpoint REJECTING the token ends the session (null →
    // logout below). A network blip or a 5xx from the gateway is transient:
    // rethrow so the caller fails this one request and keeps the still-valid
    // refresh token for the next attempt.
    const status = axios.isAxiosError(err) ? err.response?.status : undefined;
    if (status === 400 || status === 401) return null;
    throw err;
  }
}

/**
 * Restore the in-memory access token after a page load. The access token is
 * deliberately NOT persisted (see store/auth.ts) — this trades it back in
 * from the persisted refresh token on boot. Resolves false when the session
 * is truly over (refresh missing or rejected).
 */
export async function bootstrapAccess(): Promise<boolean> {
  // Share the interceptor's single-flight promise: a boot-time 401 retry
  // racing this call must not rotate the refresh token twice (the second
  // POST would carry the just-blacklisted token and read as a revocation).
  if (!refreshPromise) {
    refreshPromise = refreshAccessToken().finally(() => {
      refreshPromise = null;
    });
  }
  try {
    return (await refreshPromise) != null;
  } catch {
    // Transient failure: report "not restored" without touching the store —
    // the login screen's retry (or the next request's 401 path) tries again.
    return false;
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
      let newAccess: string | null;
      try {
        newAccess = await refreshPromise;
      } catch {
        // Transient refresh failure (network/5xx): fail THIS request only.
        // The session survives; the next 401 retries the refresh.
        return Promise.reject(error);
      }
      if (newAccess) {
        original.headers.set("Authorization", `Bearer ${newAccess}`);
        return api(original);
      }
      // The refresh token was rejected: the session is over everywhere.
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
  if (count > cap * pageSize) {
    // The cap exists as a runaway guard, but hitting it must never be silent —
    // this function's whole purpose is lists that aren't quietly truncated.
    console.warn(
      `fetchAllPages(${path}): fetched ${cap * pageSize} of ${count} rows (cap ${cap} pages)`,
    );
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
