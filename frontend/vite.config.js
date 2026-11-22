import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Inside Docker the API is reachable at http://api:8000.
// When Vite runs on the host, fall back to localhost.
const apiTarget = process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    // Docker Desktop on Windows does not always forward file events into the
    // container, so polling keeps hot reload reliable.
    watch: { usePolling: process.env.VITE_USE_POLLING === "true" },
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
