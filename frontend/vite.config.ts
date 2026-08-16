/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Long-cacheable vendor chunks: app-code changes don't invalidate the
        // framework bundle in users' browsers. reactflow is NOT listed — it
        // splits into its own lazy chunk via the dynamic import in
        // StrategiesPanel and never loads unless the graph builder opens.
        manualChunks: {
          "vendor-react": ["react", "react-dom"],
          "vendor-data": ["@tanstack/react-query", "axios", "zustand"],
        },
      },
    },
  },
  test: {
    environment: "node",
    // The vitest suite lives with the rest of the tests at the repo root
    // (test/frontend); the files import back into frontend/src by relative
    // path, so module resolution still starts inside this package.
    dir: "../test/frontend",
    include: ["**/*.test.ts"],
  },
});
