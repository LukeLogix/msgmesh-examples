// server.js — chat-web's minimal token-broker backend (zero extra dependencies, pure Node built-in http + fetch).
//
// It does two things:
//   1. POST /api/token — uses the server-side long-lived key to trade the platform for a
//      short-lived, scoped-down data-plane token, returned to the frontend as-is. The long-lived
//      key lives only in this backend and never reaches the browser.
//   2. Serves the dist/ static frontend (Vite build output), with an SPA fallback to index.html.
//
// This is exactly the best practice this template teaches: no long-lived key in the frontend;
// the backend mints short-lived tokens.
//
// Multi-room isolation: one topic is split into "rooms" (room = Kafka record key). When
// MSGMESH_ROOMS is set, token minting scopes the capabilities' rooms down to "the rooms this user
// may access" — the token can only publish / subscribe to those rooms ({ room } in both
// directions, SDK 0.2.0+); overreach gets a 403 from the platform (true isolation, not reliant on the frontend being honest).
// To run: `npm run build` to produce dist/, then `node --env-file=.env server.js` (Node >= 20.6).

import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join, normalize, extname, sep } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const DIST = join(HERE, "dist");

// Server-side config (never enters the frontend). CONTROL_PLANE is the governance plane,
// where the token-minting endpoint lives.
const API_KEY = process.env.MSGMESH_API_KEY;
const CONTROL_PLANE = (process.env.MSGMESH_CONTROL_PLANE_URL || "http://localhost:8080").replace(/\/$/, "");
const TOPIC = process.env.MSGMESH_TOPIC || "chat.lobby";
const PORT = Number(process.env.PORT) || 8787;

// ROOMS — the allow-set of rooms available to the user this broker represents (comma-separated;
// a real app would derive it from the signed-in identity). Token minting scopes the capabilities'
// rooms down to this set: the token can only send/receive in these rooms, overreach returns 403.
// Empty/unset = omit rooms = no room restriction (backward compatible, a single lobby, same
// behavior as the older version).
const ROOMS = (process.env.MSGMESH_ROOMS || "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

// Scope-down template: the minted token may only publish+subscribe to this one topic, TTL 5
// minutes; when ROOMS is set, its rooms are further narrowed to that set (room isolation). The
// platform collapses it into a subset of the caller key's capabilities (overreach returns 403), so
// nothing written here can broaden anything — the long-lived key itself must be able to
// send/receive all rooms of this topic (empty rooms = unrestricted) for minting to succeed.
const TOKEN_TTL_SECONDS = 300;
const tokenRequestBody = () => {
  const rule = { ops: ["publish", "subscribe"], topics: [TOPIC] };
  // Attach rooms only when ROOMS is set (scoping the token down to those rooms);
  // unset = omitted = no room restriction.
  if (ROOMS.length) rule.rooms = ROOMS;
  return JSON.stringify({ capabilities: [rule], ttl_seconds: TOKEN_TTL_SECONDS });
};

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".map": "application/json; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
};

function sendJSON(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(body);
}

// mintToken calls the platform's POST /v1/tokens on the frontend's behalf and passes
// {token, expires_in} straight back. Every failure returns a generic message and is logged
// server-side only — never leak the long-lived key or the upstream body into the frontend response.
async function mintToken(res) {
  if (!API_KEY || API_KEY === "replace-me") {
    console.error("[token-broker] MSGMESH_API_KEY not set — cannot mint tokens (fill in .env)");
    return sendJSON(res, 500, { error: "token broker not configured" });
  }

  let upstream;
  try {
    upstream = await fetch(`${CONTROL_PLANE}/v1/tokens`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${API_KEY}`,
        "content-type": "application/json",
      },
      body: tokenRequestBody(),
    });
  } catch (err) {
    // Cannot reach the control plane (wrong address / service down / network) — return 502,
    // details logged server-side only.
    console.error("[token-broker] failed to reach control plane:", err?.message || err);
    return sendJSON(res, 502, { error: "token broker: cannot reach control plane" });
  }

  if (!upstream.ok) {
    // Upstream returned non-2xx (invalid key / insufficient capability / TTL over limit...) —
    // to the frontend this is a backend configuration problem, so return 502. Log the status and
    // body server-side for troubleshooting only; do not forward the upstream body to the frontend
    // (avoids leaking configuration details).
    const detail = await upstream.text().catch(() => "");
    console.error(`[token-broker] control plane responded ${upstream.status}: ${detail}`);
    return sendJSON(res, 502, { error: `token broker: control plane error (${upstream.status})` });
  }

  let data;
  try {
    data = await upstream.json();
  } catch {
    console.error("[token-broker] control plane returned non-JSON");
    return sendJSON(res, 502, { error: "token broker: malformed control plane response" });
  }

  // The SDK's getToken only needs { token, expires_in }; forward just these two fields.
  return sendJSON(res, 200, { token: data.token, expires_in: data.expires_in });
}

// serveStatic serves files from dist/; anything not found falls back to index.html (SPA fallback).
async function serveStatic(req, res) {
  // Only GET/HEAD may fetch static assets.
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405, { allow: "GET, HEAD" });
    return res.end();
  }

  // Normalize the path and block directory traversal: the resolved path must stay inside dist/.
  const urlPath = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
  let filePath = normalize(join(DIST, urlPath));
  if (filePath !== DIST && !filePath.startsWith(DIST + sep)) {
    res.writeHead(403);
    return res.end("forbidden");
  }
  if (urlPath.endsWith("/")) filePath = join(filePath, "index.html");

  try {
    const body = await readFile(filePath);
    const type = MIME[extname(filePath).toLowerCase()] || "application/octet-stream";
    res.writeHead(200, { "content-type": type });
    return res.end(req.method === "HEAD" ? undefined : body);
  } catch {
    // File not found: a single-page app always falls back to index.html.
    try {
      const index = await readFile(join(DIST, "index.html"));
      res.writeHead(200, { "content-type": MIME[".html"] });
      return res.end(req.method === "HEAD" ? undefined : index);
    } catch {
      // Not even index.html — most likely not built yet.
      res.writeHead(404, { "content-type": MIME[".txt"] });
      return res.end("Not built yet: run `npm run build` to produce dist/, then start the server.");
    }
  }
}

const server = createServer((req, res) => {
  const { pathname } = new URL(req.url, "http://localhost");

  if (pathname === "/api/token") {
    if (req.method !== "POST") {
      res.writeHead(405, { allow: "POST" });
      return res.end();
    }
    req.resume(); // the frontend sends no body, but drain the request stream anyway so the connection is not left hanging
    return void mintToken(res);
  }

  return void serveStatic(req, res);
});

server.listen(PORT, () => {
  console.log(`chat-web token-broker up → http://localhost:${PORT}`);
  console.log(`  control plane: ${CONTROL_PLANE}`);
  console.log(`  topic:         ${TOPIC}`);
  console.log(`  rooms:         ${ROOMS.length ? ROOMS.join(", ") : "(unrestricted; MSGMESH_ROOMS not set)"}`);
  console.log(`  static root:   ${DIST}`);
  if (!API_KEY || API_KEY === "replace-me") {
    console.warn("  ⚠ MSGMESH_API_KEY not set — /api/token will return 500; fill in .env and restart.");
  }
});
