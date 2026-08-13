import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".");
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || "http://127.0.0.1:18000";

  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        "/api": apiProxyTarget,
        "/health": apiProxyTarget,
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: "./src/test/setup.ts",
      css: true,
      globals: true,
    },
  };
});
