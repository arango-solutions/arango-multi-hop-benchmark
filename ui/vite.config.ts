/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `base: "./"` keeps every asset URL relative so the built SPA works under any
// BYOC proxy subpath (e.g. /_service/uds/_global/<name>/frontend/) without a
// rebuild. The dev proxy forwards API calls to the FastAPI backend on :8000.
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/connection": "http://localhost:8000",
      "/config": "http://localhost:8000",
      "/run": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/dashboard": "http://localhost:8000",
      "/adhoc": "http://localhost:8000",
      "/rag_eval": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
