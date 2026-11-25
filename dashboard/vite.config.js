import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dashboard talks to Django through this dev server, so the browser sees ONE
// origin: the session and CSRF cookies just work, and the WebSocket's Origin
// header matches ALLOWED_HOSTS. (Deliberately no `changeOrigin`: Django must see
// the same host the browser used, or its CSRF origin check fails.) 127.0.0.1, not
// "localhost": Node resolves that to IPv6 (::1) first, and runserver listens on IPv4.
const DJANGO = process.env.DJANGO_URL || "http://127.0.0.1:8000";

// The static website build (GitHub Pages, see .github/workflows/pages.yml) sets
// VITE_SITE_ONLY=1 and VITE_BASE="./": relative asset paths, so it works under any
// repo path such as /tokenguard/. Everything else builds exactly as before.
const SITE_ONLY = process.env.VITE_SITE_ONLY === "1";

export default defineConfig({
  base: process.env.VITE_BASE || "/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/tokenguard": DJANGO,
      "/ws": { target: DJANGO, ws: true },
    },
  },
  build: { outDir: "dist", sourcemap: !SITE_ONLY },
});
