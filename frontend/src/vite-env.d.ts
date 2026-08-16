/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute API base (e.g. https://quantai-api.onrender.com/api/v1). Falls back to same-origin /api/v1. */
  readonly VITE_API_BASE?: string;
  /** Absolute WebSocket base (e.g. wss://quantai-api.onrender.com). Falls back to same-origin ws(s)://. */
  readonly VITE_WS_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
