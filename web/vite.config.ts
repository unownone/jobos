import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = process.env.HUB_PROXY || "http://127.0.0.1:8787";
const proxy = {
  "/api": api,
  "/ws": { target: api.replace(/^http/, "ws"), ws: true },
  "/health": api,
  "/ready": api,
  "/llms.txt": api,
  "/agents.txt": api,
  "/a2a": api,
  "/.well-known": api,
};

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  preview: { proxy },
});
