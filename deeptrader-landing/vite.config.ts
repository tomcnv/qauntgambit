import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

// https://vitejs.dev/config/
export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: 3000,
    // Explicit host allowlist for local reverse-proxy domains.
    allowedHosts: [
      "localhost",
      "127.0.0.1",
      "quantgambit.local",
      "dashboard.quantgambit.local",
      "bot.quantgambit.local",
    ],
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
