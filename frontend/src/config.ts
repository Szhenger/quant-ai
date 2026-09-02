/**
 * Where the backend lives. Absolute bases for split-origin deployments (static
 * frontend + API service); default to same-origin relative paths, which the
 * Vite dev proxy serves (see vite.config.ts and runtime/render.yml).
 */
export const API_BASE = import.meta.env.VITE_API_BASE || "/api/v1";
export const WS_BASE =
  import.meta.env.VITE_WS_BASE || window.location.origin.replace(/^http/, "ws");
