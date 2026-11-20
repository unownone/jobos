import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  base: "/static/app/",
  build: {
    outDir: path.resolve(__dirname, "../app/static/app"),
    emptyOutDir: true,
    manifest: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8787",
      "/static": "http://127.0.0.1:8787",
      "/brand": "http://127.0.0.1:8787",
      "/health": "http://127.0.0.1:8787",
    },
  },
  test: { environment: "jsdom", setupFiles: "./src/test-setup.ts" },
});