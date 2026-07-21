import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const plannerOrigin = process.env.PLOVER_PLANNER_ORIGIN ?? "http://127.0.0.1:8000";
const frontendPort = Number.parseInt(process.env.PLOVER_FRONTEND_PORT ?? "5173", 10);

export default defineConfig({
  plugins: [react()],
  build: {
    target: "esnext"
  },
  optimizeDeps: {
    esbuildOptions: {
      target: "esnext"
    }
  },
  server: {
    port: Number.isNaN(frontendPort) ? 5173 : frontendPort,
    proxy: {
      "/api": plannerOrigin,
      "/health": plannerOrigin
    }
  }
});
