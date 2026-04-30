import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const BACKEND = "http://127.0.0.1:8000";
const WS_BACKEND = "ws://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/users": BACKEND,
      "/agent": BACKEND,
      "/health": BACKEND,
      "/ws": { target: WS_BACKEND, ws: true },
    },
  },
});
