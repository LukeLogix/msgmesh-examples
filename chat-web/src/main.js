// chat-web — minimal web chat room: receives in realtime with @msgmesh/sdk's stream() (SSE), sends with publish().
// Auth goes through a token-broker: the frontend holds no long-lived key; the backend (server.js)
// mints short-lived, scoped-down tokens at /api/token.
// The gateway / realtime URLs and the topic are non-sensitive, so Vite injects them (see .env.example).
//
// Multi-room: one topic is split into "rooms". Both directions pass { room } (SDK 0.2.0+):
// publish targets that room, subscribe receives only that room. Which rooms are available is decided by
// the rooms of the backend-minted token and enforced by the platform (overreach returns 403); the
// frontend's VITE_MSGMESH_ROOMS is only used to draw the room menu — it is not an authorization boundary.
//
// transport: SSE (stream) by default. Add ?transport=ws to the URL to use WebSocket (streamWs) instead —
// same interface, same room support. It demonstrates the alternative "WS receives rooms too" path.
import { MsgMesh } from "@msgmesh/sdk";

const env = import.meta.env;
const cfg = {
  gatewayUrl: env.VITE_MSGMESH_GATEWAY_URL,
  realtimeUrl: env.VITE_MSGMESH_REALTIME_URL,
  topic: env.VITE_MSGMESH_TOPIC || "chat.lobby",
  // Room list for the menu (frontend UI only; must match the backend's MSGMESH_ROOMS).
  // Empty = a single lobby, no menu shown.
  rooms: (env.VITE_MSGMESH_ROOMS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean),
};

// Read the current room and transport from the URL. When the room is not in the allow-list
// (or there is no list), fall back to the first room / no room.
const params = new URLSearchParams(location.search);
const urlRoom = params.get("room");
let activeRoom =
  urlRoom && (cfg.rooms.length === 0 || cfg.rooms.includes(urlRoom))
    ? urlRoom
    : cfg.rooms[0] || "";
let useWs = params.get("transport") === "ws";

// Fetch a short-lived data-plane token from the backend token-broker. The SDK caches it, refetches
// before expiry, and swaps in a new one on reconnect, so no lifetime management is needed here.
// The response must be { token, expires_in }. The token's rooms were already scoped down by the
// backend to cover all rooms this user may access, so one token switches between allowed rooms
// without re-minting on every switch.
async function getToken() {
  const r = await fetch("/api/token", { method: "POST" });
  if (!r.ok) throw new Error("token-broker " + r.status);
  return r.json();
}

const $ = (id) => document.getElementById(id);
const messagesEl = $("messages");
const form = $("composer");
const textInput = $("text");
const nameInput = $("name");
const statusEl = $("status");
const roomsEl = $("rooms");
const transportEl = $("transport");
const sendBtn = form.querySelector("button");

// One random nickname per tab, to tell "own" messages apart from everyone else's.
nameInput.value = "guest-" + Math.random().toString(36).slice(2, 6);

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.dataset.kind = kind || "";
}

function addMessage({ user, text, ts }, mine) {
  const li = document.createElement("li");
  li.className = "msg" + (mine ? " mine" : "");

  const who = document.createElement("span");
  who.className = "who";
  who.textContent = user || "anon";

  const body = document.createElement("span");
  body.className = "body";
  body.textContent = text ?? "";

  const time = document.createElement("time");
  time.textContent = new Date(ts || Date.now()).toLocaleTimeString();

  li.append(who, body, time);
  messagesEl.append(li);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// Draw the room menu (only when VITE_MSGMESH_ROOMS is set). Clicking switches to that room.
function renderRooms() {
  roomsEl.textContent = "";
  if (cfg.rooms.length === 0) return;
  for (const room of cfg.rooms) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "room-btn" + (room === activeRoom ? " active" : "");
    btn.textContent = "# " + room;
    btn.addEventListener("click", () => switchRoom(room));
    roomsEl.append(btn);
  }
}

// Show the current transport (SSE / WS) badge.
function renderTransport() {
  transportEl.textContent = useWs ? "WS" : "SSE";
  transportEl.title = useWs
    ? "WebSocket (streamWs); remove ?transport=ws from the URL to switch back to SSE"
    : "Server-Sent Events (stream); add ?transport=ws to the URL to use WebSocket";
}

// When the URL config is incomplete, say so on screen instead of connecting anyway
// (avoids a pile of cryptic console errors). The token comes from the backend /api/token, so the
// frontend never sees the key; whether the token-broker is up is reported when the SDK calls it.
let mq;
let stopStream = null; // stop function of the current subscription (stop the old one before switching room / transport)

function start() {
  mq = new MsgMesh({
    getToken,
    gatewayUrl: cfg.gatewayUrl,
    realtimeUrl: cfg.realtimeUrl,
  });

  // WS chosen but the installed SDK is an older version without streamWs:
  // fall back to SSE with a hint instead of letting the whole example break.
  if (useWs && typeof mq.streamWs !== "function") {
    console.warn("This @msgmesh/sdk has no streamWs; falling back to SSE. Upgrade the SDK to use the WebSocket transport.");
    useWs = false;
  }

  renderTransport();
  renderRooms();
  subscribe();

  // Send: publish a JSON object, with room targeting the room (the platform routes rooms by record
  // key and checks the token's rooms — outside the allow-set returns 403). The message flows back
  // through the subscription and onMessage renders it (including our own).
  // Both directions use the same word, room: subscribe passes { room }, publish passes { room }
  // (SDK 0.2.0+; earlier versions called this option key). package.json requires ^0.3.0, the
  // version that added onMessage's meta argument — see subscribe() for what it buys.
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = textInput.value.trim();
    if (!text) return;
    const user = nameInput.value.trim() || "anon";
    textInput.value = "";
    try {
      const opts = activeRoom ? { room: activeRoom } : {};
      await mq.publish(cfg.topic, { user, text, ts: Date.now() }, opts);
    } catch (err) {
      console.error("publish failed:", err);
      setStatus("Send failed: " + (err?.message || err), "error");
      textInput.value = text; // restore the text for an easy retry
    }
  });
}

// The message value is a string — we publish JSON, so parse it first.
function parseMessage(value) {
  try {
    return JSON.parse(value);
  } catch {
    return { text: value };
  }
}

let session = 0; // bumps on every (re)subscribe, so a stale in-flight history fetch cannot render into the wrong room

// subscribe opens one realtime subscription for the current transport and activeRoom,
// reclaiming the previous one (if any). It first fetches the recent backlog with history()
// (SDK 0.2.0+) so a late joiner does not face a blank screen, then starts the live stream from the
// cursor the history page handed back, deduping the overlap by message id (SDK 0.3.0+).
// stream / streamWs share the same interface;
// the fourth argument { room } receives only that room; omit it to receive the whole topic.
async function subscribe() {
  stopStream?.();
  stopStream = null;
  const mySession = ++session;

  // Backlog first: latest 50 messages of the topic / current room, rendered before going live.
  // The backlog is a nice-to-have — a platform without the history endpoint (or a transient
  // error) must not block the live chat, so failures only log and we go straight to the stream.
  const backlogIds = new Set(); // ids of the backlog messages, to drop the history/live overlap
  let from; // resume cursor handed back by history(); guaranteed replayable when issued
  if (typeof mq.history === "function") {
    setStatus("Loading recent messages…", "pending");
    try {
      const page = await mq.history(
        cfg.topic,
        activeRoom ? { room: activeRoom, limit: 50 } : { limit: 50 },
      );
      if (mySession !== session) return; // switched room / transport while fetching
      for (const m of page.messages) {
        const payload = parseMessage(m.value);
        addMessage(payload, payload.user === nameInput.value.trim());
        backlogIds.add(m.id);
      }
      from = page.resume_from || undefined;
    } catch (err) {
      if (mySession !== session) return;
      console.warn("history backlog unavailable, going straight to live:", err?.message || err);
    }
  }

  // onMessage receives the message value and its coordinates: (value, meta), where meta is
  // { id, partition, offset } (SDK 0.3.0+). meta.id is byte-for-byte the same "<partition>-<offset>"
  // that history() puts on every message, so one Set of ids spans the history/live seam.
  const onMessage = (data, meta) => {
    // Drop the overlap between backlog and live: delivery is at-least-once and the resume window
    // deliberately overlaps, so a backlog message can arrive again from the stream. Matching by
    // meta.id is exact. (Comparing message bodies, which is all that was possible before 0.3.0,
    // cannot tell two genuinely identical messages apart — heartbeats, status pings and retries
    // are routinely byte-identical — and swallows one of them.)
    //
    // Fallback when meta is undefined — the frame carried no parseable id (a non-msgmesh server,
    // or a WS frame outside the resume envelope): render the message. It cannot be matched against
    // the backlog either way, and showing a rare duplicate beats silently dropping a real message.
    // This is the same fail-open choice the SDK makes for its own per-partition dedupe.
    if (meta && backlogIds.has(meta.id)) return;
    const payload = parseMessage(data);
    addMessage(payload, payload.user === nameInput.value.trim());
  };
  const onError = (err) => {
    console.error("stream error:", err);
    // With a room-scoped token, subscribing to a room outside the allow-set is blocked by the
    // platform (403); everything else is mostly transient disconnects the SDK reconnects from.
    setStatus("Disconnected or room not authorized; the SDK reconnects automatically (see console).", "error");
  };
  // from = history()'s resume_from: the live stream picks up right where the backlog ended,
  // instead of starting "now" and missing whatever arrived in between.
  const opts = {};
  if (activeRoom) opts.room = activeRoom;
  if (from) opts.from = from;

  // stream()/streamWs() return a stop function; no need to stop while the page lives,
  // but switching room / transport must stop the old subscription first.
  stopStream = useWs
    ? mq.streamWs(cfg.topic, onMessage, onError, opts)
    : mq.stream(cfg.topic, onMessage, onError, opts);

  // Neither SSE nor WS exposes a definite "connected and messages guaranteed" moment;
  // optimistically report ready — a real disconnect overrides it via onError.
  const where = activeRoom ? `${cfg.topic} / #${activeRoom}` : cfg.topic;
  setStatus(`Connected (${useWs ? "WS" : "SSE"}) — ${where} (waiting for messages)`, "ok");
}

// switchRoom switches between allowed rooms: update the URL (shareable), clear the screen,
// and re-subscribe + publish with the same token.
function switchRoom(room) {
  if (room === activeRoom) return;
  activeRoom = room;

  const u = new URL(location.href);
  u.searchParams.set("room", room);
  history.replaceState(null, "", u);

  messagesEl.textContent = "";
  renderRooms();
  subscribe();
}

// ── Bootstrap — keep this LAST in the file ───────────────────────────────────
// `function` declarations hoist, so calling start() from higher up "works"; `let` does not.
// Starting the app before the module has finished evaluating means any `let` declared below the
// call site (mq, stopStream, session…) is still in its temporal dead zone, and the first access
// throws "Cannot access 'x' before initialization". The page then dies on load with the status
// stuck at "Initializing…" and nothing in the network tab — it never got as far as a request.
// Running the bootstrap last makes that whole class of bug impossible, so do not move it up.
if (!cfg.gatewayUrl || !cfg.realtimeUrl) {
  setStatus("Not configured: copy .env.example to .env, fill in the gateway/realtime URLs, then rebuild.", "error");
  sendBtn.disabled = true;
} else {
  start();
}
