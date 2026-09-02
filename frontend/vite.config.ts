/// <reference types="vitest/config" />
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The vitest files live outside this package (test/frontend) and import the
// libraries they render with (react, testing-library, ...) as bare names.
// Module resolution walks up from the importing FILE, so from test/frontend
// those names would never reach frontend/node_modules; these aliases point
// each one back here. Exact-match regexes so `react` never captures
// `react-dom`; the `$1` keeps deep imports (react/jsx-runtime) working.
const fromNodeModules = (name: string) => ({
  find: new RegExp(`^${name.replace(/[/@.]/g, "\\$&")}(/.*)?$`),
  replacement: path.resolve(__dirname, "node_modules", name) + "$1",
});
const TEST_LIBS = [
  "react",
  "react-dom",
  "@tanstack/react-query",
  "axios",
  "zustand",
  "@testing-library/react",
  "@testing-library/dom",
  "@testing-library/user-event",
  "@testing-library/jest-dom",
];

export default defineConfig({
  plugins: [react()],
  server: {
    // The test files (and their setup file) live one level up, in test/frontend.
    fs: { allow: [path.resolve(__dirname, "..")] },
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
    // Pure-logic tests run in node; a file that renders declares
    // `@vitest-environment jsdom` in its docblock.
    environment: "node",
    // The vitest suite lives with the rest of the tests at the repo root
    // (test/frontend); the files import back into frontend/src by relative
    // path, so module resolution still starts inside this package.
    dir: "../test/frontend",
    include: ["**/*.test.{ts,tsx}"],
    setupFiles: ["../test/frontend/setup.ts"],
    alias: TEST_LIBS.map(fromNodeModules),
  },
});
