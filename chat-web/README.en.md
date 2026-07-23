[繁體中文](./README.md) | **English**

# chat-web — MsgMesh web real-time chat starter

A minimal browser chat room: many people connect to the same topic and, as they send, see everyone's messages in real time. No frontend framework — just Vite + vanilla JS — so you can directly follow every line of how the SDK is used.

This template **uses a token-broker by default**: no long-lived key in the frontend, with authentication proxied by a minimal backend (`server.js`). This is exactly the correct way to put real-time send/receive in the browser. It also demonstrates both **multi-room isolation** and **two real-time transports (SSE / WebSocket)**.

- **Receive**: `@msgmesh/sdk`'s [`stream()`](https://www.npmjs.com/package/@msgmesh/sdk) (SSE, the browser-native `EventSource`, connecting to `GET {realtime}/v1/topics/{topic}/sse`); or `streamWs()` (WebSocket, same interface). Both take an optional `{ room }` to receive only one room.
- **Send**: `publish()` — `POST {gateway}/v1/topics/{topic}/messages`, sending `{ user, text, ts }` JSON; use `{ key: room }` to specify the room.
- **Authentication**: the frontend holds no key and instead uses the SDK's `getToken` to obtain a short-lived token from the backend `/api/token` (see "token-broker" below). The token's capabilities have already been **scoped down by the backend to the rooms this user may access**, enforced by the platform (see "Multiple rooms and isolation").

## What the token-broker is

Once a long-lived API key ends up in the browser bundle, any visitor can see it — which is to say it's leaked. The token-broker keeps the key on the backend, and the frontend only gets short-lived, scoped-down tokens:

```
Browser (SDK getToken)
    │  POST /api/token             ← frontend holds no long-lived key
    ▼
server.js (holds the long-lived MSGMESH_API_KEY)
    │  POST {controlPlane}/v1/tokens   Authorization: Bearer <key>
    │  scoped-down body: { capabilities:[{ops:[publish,subscribe],topics:[TOPIC],rooms:[<accessible rooms>]}], ttl_seconds:300 }
    ▼
platform control-plane  →  returns { token, expires_in }  →  passed straight back to the frontend
```

Once the SDK has a token it caches it automatically, refetches before it expires, and swaps in a new one on SSE reconnect, so the "5-minute TTL" is invisible to the user. The platform narrows the token's capabilities to a **subset** of the backend key's (only narrower is allowed; overreach returns 403), so even a misconfigured `server.js` cannot broaden them. The `rooms` in the scoped-down body is what hard-codes "which rooms this token may touch" into the credential (see the next section).

## Multiple rooms and isolation

A `room` = a sub-channel under a single topic, physically the **Kafka record key**. On publish you tag the room with the key; on subscribe you use the room to receive only that room; which rooms are available is **decided by the token minted by the backend and enforced by the platform** — this is "true isolation", not reliant on the frontend being honest.

Data flow (frontend room → token scope-down → subscribe/publish):

```
1. Frontend picks a room (URL ?room= or the menu) → SDK getToken → POST /api/token
2. server.js mints a token from the "rooms this user may access" allow-set (MSGMESH_ROOMS):
     capabilities:[{ ops:[publish,subscribe], topics:[TOPIC], rooms:[<allow-set>] }]
   The platform narrows the token's capabilities to a subset of the backend key's (overreach → 403)
3. The frontend takes this token:
     subscribe  stream / streamWs(topic, …, { room })   → realtime pushes only that room (?room)
     publish    publish(topic, body, { key: room })       → the platform routes to that room by record key
4. The platform checks the token's rooms on every receive / send:
     ?room / ?key not in the allow-set → 403. Even if the frontend is tampered to point at someone
     else's room it gets nothing — the token simply never authorized it.
```

- **The available rooms are decided by the backend**: the frontend's `VITE_MSGMESH_ROOMS` is only used to draw the menu; the real authorization boundary is the **backend token's `rooms`** (`MSGMESH_ROOMS`). Generate `MSGMESH_ROOMS` per logged-in identity and you get "a set of rooms per user / per tenant" — multi-tenant isolation.
- **One token covers all of your own rooms**: the token's `rooms` cover the user's "all accessible rooms", so switching between allowed rooms needs no new token; only switching outside the allow-set is blocked.
- **Don't want rooms at all**: leave `MSGMESH_ROOMS` and `VITE_MSGMESH_ROOMS` empty; omitting `rooms` = no room restriction = a single lobby, behaving like the older version.
- **Only realtime supports per-room**: an SSE / WS subscription can carry `?room=` to precisely receive a single room; but poll / consume (long-polling the whole topic) is a **firehose** where room-scoped credentials don't work (the platform returns 403) — for fine-grained rooms, use realtime. See [`agent-notifier/README.en.md`](../agent-notifier/README.en.md) for details.

> Version note: the publish-side `publish(…, { key })` has been supported since `@msgmesh/sdk` 0.1.3; the **subscribe-side `{ room }` filtering of `stream`/`streamWs`** requires the SDK version released together with the multi-room platform (older versions ignore the parameter and receive the whole topic). This template ships together with the multi-room platform.

## Receiving over WebSocket (streamWs)

SSE is the default. Add **`?transport=ws`** to the URL to switch to the SDK's `streamWs` (WebSocket) for receiving — the interface is identical to `stream` and also takes `{ room }`:

```js
// SSE (default)
mq.stream(topic, onMsg, onErr, { room });
// WebSocket: same interface, same room filtering, SDK manages reconnection
mq.streamWs(topic, onMsg, onErr, { room });
```

Good for cases where SSE is blocked by an intermediary (proxy / firewall), or where you already have WebSocket infrastructure. `streamWs` uses the browser-native `WebSocket` (built into all modern browsers; on Node it needs ≥ 22, or switch to `subscribe` long-polling). The `SSE` / `WS` badge in the title bar shows which one is currently in use.

## Run it

```bash
npm install
cp .env.example .env       # fill in MSGMESH_API_KEY and other values (see "Configuration" below)
npm run build              # Vite bundles the frontend into dist/
node --env-file=.env server.js   # start the token-broker + serve dist/, default http://localhost:8787
```

Open http://localhost:8787, enter a nickname, and send a message; open another tab and it receives it in real time.

- **Try multiple rooms**: the `# lobby / # support / # random` menu in the title bar switches rooms (equivalent to the URL `?room=support`); two tabs see each other only in the same room, and different rooms are isolated from one another.
- **Try WebSocket**: add `?transport=ws` to the URL (e.g. `http://localhost:8787/?room=support&transport=ws`) to receive via `streamWs`; the badge will show `WS`.
- `--env-file` needs **Node ≥ 20.6**. If you use `npm start` (= `node server.js`), it won't read `.env` on its own, so load the environment variables yourself first (e.g. `export $(grep -v '^#' .env | xargs)`).
- After changing the frontend (`src/` / `index.html`), re-run `npm run build`; after changing `.env` or `server.js`, restart the server.

### Hot reload during development

To edit the frontend and see the effect live, open two terminals:

```bash
node --env-file=.env server.js   # terminal A: token-broker (:8787)
npm run dev                       # terminal B: Vite dev server (:5173)
```

`vite.config.js` already proxies `/api` to `:8787`, so when developing at http://localhost:5173, `/api/token` is forwarded to the backend. (If the ports differ, set `PORT` to keep both sides consistent.)

### What you need

- A running MsgMesh (see "Common prerequisites" in the repo root README).
- An API key that can both **publish and subscribe** to that topic, placed in the backend `.env` as `MSGMESH_API_KEY`.

## Configuration

Everything goes through `.env` (see `.env.example`), in two sections. **The topic and rooms in both sections must match.**

### Backend (used by `server.js`, never enters the frontend bundle)

| Variable | Purpose |
| --- | --- |
| `MSGMESH_API_KEY` | Long-lived API key (publish + subscribe capability, able to send/receive in the rooms below), used to mint short-lived tokens. Backend only. |
| `MSGMESH_CONTROL_PLANE_URL` | Control-plane address (the `POST /v1/tokens` that mints tokens hits this); defaults to `http://localhost:8080` locally |
| `MSGMESH_TOPIC` | Chat topic; must match the frontend's `VITE_MSGMESH_TOPIC` |
| `MSGMESH_ROOMS` | This user's "accessible rooms" allow-set (comma-separated); the token is scoped down to this set when minted (**the real authorization boundary**). Empty = no room restriction |
| `PORT` | Port the token-broker listens on; defaults to `8787` |

### Frontend (the `VITE_` prefix gets bundled; all are non-sensitive values)

| Variable | Purpose |
| --- | --- |
| `VITE_MSGMESH_GATEWAY_URL` | Send/receive service (publish hits this) |
| `VITE_MSGMESH_REALTIME_URL` | Realtime service (both SSE streaming and WebSocket hit this) |
| `VITE_MSGMESH_TOPIC` | Chat topic; defaults to `chat.lobby` |
| `VITE_MSGMESH_ROOMS` | Room menu list (comma-separated), **frontend UI only**; must match the backend's `MSGMESH_ROOMS`. Empty = a single lobby |

## Production security

This template **already uses a token-broker by default**: no long-lived key in the frontend, and the backend mints short-lived, scoped-down tokens — this is exactly how production should look. When you actually deploy, also mind these:

- `.env` (containing `MSGMESH_API_KEY`) goes only on the backend, is already excluded by `.gitignore`, and must not be committed.
- Keep `MSGMESH_API_KEY`'s capabilities limited to publish + subscribe on this chat topic (least privilege); don't use an admin or wildcard key.
- `server.js` forwards only `{ token, expires_in }`, leaking neither the key nor upstream error details into the frontend response.
- "A set of rooms per user" means changing `MSGMESH_ROOMS` to be **generated dynamically from the logged-in identity** (e.g. a given tenant's room set) and filling it into `capabilities[].rooms` in the scoped-down body in `server.js` — the token can only touch those rooms, enforced by the platform, everything else a 403. This is cheaper than "one topic per room" (a shared topic + a single live-tail), with isolation still guaranteed by the credential.
- **The platform does not verify "who is speaking".** Room isolation only guarantees "which rooms you can send to / receive from"; it does not verify the `user` (sender) in the message — the nickname in this demo is self-reported by the frontend, and anyone in the same room can set `user` to someone else and **impersonate** them. Production chat must prevent impersonation: **bind the token to the logged-in user when minting it in `server.js`, and have the backend stamp / verify `user`**, rather than letting the frontend self-report its identity.

## Files

- `index.html` — UI and styling (single file, no framework; includes the room menu and the SSE/WS badge).
- `src/main.js` — reads config, obtains a token via `getToken`, receives with `stream()`/`streamWs()` (carrying `room`), sends with `publish()` (carrying `key`), switches rooms, renders messages.
- `server.js` — minimal token-broker backend: `POST /api/token` mints short-lived **room-scoped** tokens + serves the `dist/` static frontend (zero extra dependencies, pure Node built-ins).
- `vite.config.js` — proxies `/api` to the backend during development.
- `.env.example` — config template (copy it to `.env`).
