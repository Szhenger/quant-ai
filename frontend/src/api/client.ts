import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";
import { useAuthStore } from "../store/auth";

const api = axios.create({ baseURL: "/api/v1" });

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
    const res = await axios.post<{ access: string }>(
      "/api/v1/auth/token/refresh/",
      { refresh },
    );
    const access = res.data.access;
    useAuthStore.getState().setAccess(access);
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

export default api;
