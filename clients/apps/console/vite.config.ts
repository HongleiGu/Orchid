import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

import pkg from "./package.json" with { type: "json" };

// Served at https://<domain>/console/, same origin as the API. Same origin is
// what lets the key live in web storage at all: no CORS preflights, and a CSP
// of connect-src 'self' means injected script cannot ship the key elsewhere.
const BASE = "/console/";

export default defineConfig(({ mode }) => ({
  base: BASE,
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  plugins: [
    react(),
    VitePWA({
      registerType: "prompt",
      // Registration happens in UpdateBanner via the React hook, so nothing is
      // injected into index.html — no second registration, and no inline
      // script for the CSP to have to allow.
      injectRegister: false,
      manifest: {
        name: "Orchid Console",
        short_name: "Orchid",
        description: "Control an Orchid deployment: templates, runs, live progress.",
        lang: "zh-CN",
        start_url: BASE,
        scope: BASE,
        display: "standalone",
        background_color: "#0f1115",
        theme_color: "#0f1115",
        icons: [
          { src: "icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
          { src: "icon-maskable.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
        ],
      },
      workbox: {
        // Cache the app shell only. API responses are never cached: stale run
        // status or a stale attestation shown as current would be wrong in a
        // way the user cannot see.
        globPatterns: ["**/*.{js,css,html,svg}"],
        navigateFallback: `${BASE}index.html`,
        navigateFallbackDenylist: [/^\/api\//, /^\/health$/],
        runtimeCaching: [],
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    // `pnpm dev` against a local backend without CORS: proxy the API through Vite.
    proxy: {
      "/api": { target: process.env.ORCHID_DEV_API ?? "http://127.0.0.1:8000", changeOrigin: true },
      "/health": { target: process.env.ORCHID_DEV_API ?? "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: {
    sourcemap: mode !== "production",
    target: "es2020",
  },
}));
