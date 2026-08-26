// Vite config — during development (`npm run dev`), proxies /api to the token-broker backend (server.js).
// This lets "the Vite dev server (:5173) + `node --env-file=.env server.js` in another terminal"
// cooperate: the frontend requests same-origin /api/token, and the proxy forwards it to the backend.
// In production, `npm run build` output is served by server.js itself without Vite,
// so this proxy only takes effect during development.
import { defineConfig } from "vite";

// The proxy target port must match server.js's PORT (default 8787).
const BROKER_PORT = process.env.PORT || 8787;

export default defineConfig({
  server: {
    proxy: {
      "/api": `http://localhost:${BROKER_PORT}`,
    },
  },
});
