/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api is proxied to the FastAPI backend, so no CORS setup is needed.
// Override with VITE_API_BASE_URL to call a different backend directly (CORS must allow it).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": { target: process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000", changeOrigin: true } } },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/__tests__/setup.ts"] },
});
