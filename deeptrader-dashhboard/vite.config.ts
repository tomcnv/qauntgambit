/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: 5173,
    // Explicit host allowlist for local reverse-proxy domains.
    allowedHosts: [
      "localhost",
      "127.0.0.1",
      "quantgambit.local",
      "dashboard.quantgambit.local",
      "bot.quantgambit.local",
    ],
    proxy: {
      // Docs endpoints live on the Python QuantGambit API (port 3002)
      "/api/docs": {
        target: "http://localhost:3002",
        changeOrigin: true,
        secure: false,
      },
      "/api": {
        target: "http://localhost:3001",
        changeOrigin: true,
        secure: false,
      },
    },
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["**/*.test.{ts,tsx}"],
  },
});
