**English** | [繁體中文](./README.zh.md)

# msgmesh-examples

Official examples / starter templates for **MsgMesh** — each folder is a minimal "`clone` and run" starting point that shows how to use the official [`@msgmesh/sdk`](https://www.npmjs.com/package/@msgmesh/sdk) SDK to connect to MsgMesh, the multi-tenant event bus, and send and receive real-time events.

Fill in your gateway / realtime URL and an API key, and within minutes you'll have an app that can send and receive messages.

## Templates

| Folder | What it is | SDK used | Room |
| --- | --- | --- | --- |
| [`chat-web/`](./chat-web) | Browser-based real-time chat room (Vite + vanilla JS, no framework) | `stream()` (SSE) / `streamWs()` (WebSocket) to receive, `publish()` to send | ✅ per-room (scoped-down token `rooms` + platform-enforced isolation) |
| [`agent-notifier/`](./agent-notifier) | A Node script that watches events — the "event layer" for AI agents / backends | `subscribe()` long-polling to process every event | ⛔ firehose (the whole topic; room-scoped credentials won't work) |

### Which integrations support rooms

A `room` = a sub-channel under a single topic (physically = the Kafka record key). Publish with `publish(topic, body, { key: room })` to tag a room; **whether you can receive only one room depends on the integration type**:

- **Realtime (SSE `stream` / WebSocket `streamWs`)** supports **per-room**: pass `{ room }` when subscribing to receive only that room; combine it with a backend token-broker that scopes the token's `rooms` down to "the rooms this user may access", and the platform enforces the isolation (403 on overreach). See `chat-web`.
- **Poll / consume (`subscribe` long-polling)** is a **firehose**: it consumes every message of the whole topic with no room filtering; a call with room-scoped credentials is rejected with **403**. For whole-tenant consumption use a key with **no room restriction** and split by reading `msg.key` yourself. See `agent-notifier`.

## Common prerequisites

1. **A running MsgMesh instance.** Point the gateway / realtime / control-plane URLs in each template's `.env` at your instance — one you **self-host**, or the address of your **hosted account** (obtained by registering in the panel; see below). When self-hosting locally, the default ports are control-plane `:8080` / gateway `:8081` / realtime `:8082`.

2. **An API key.** Issued after registering an account in the panel (the plaintext is shown only once). Pick the scope by the capabilities each template needs:
   - `agent-notifier` only receives → needs a **consumer** key (or a key that includes the `subscribe` capability).
   - `chat-web` both receives and sends → needs a key that can both **publish + subscribe**.

3. **Node ≥ 18 (≥ 20.6 recommended).** Every template's send/receive uses the SDK's built-in `fetch` (Node 18+). The `chat-web` token-broker (`server.js`) and `agent-notifier` both read `.env` via `--env-file`, which needs Node ≥ 20.6 (alternative approaches are in each README).

Each template ships its own `README.md` (how to `npm install && npm run …`) and `.env.example`.

## Security notes

- **Never commit an API key into the repo.** Keep it only in a local `.env` (already excluded by `.gitignore`); `.env.example` holds placeholder values only.
- `chat-web` **uses a token-broker by default**: the key lives only in its bundled minimal backend (`server.js`), and the frontend holds no long-lived key — the backend holds the long-lived key and exchanges it for short-lived, scoped-down tokens, which the frontend obtains via the SDK's `getToken`. The scoping also covers **rooms**: the token's `rooms` are narrowed to "the rooms this user may access", enforced by the platform, so different rooms are isolated from one another. This is the correct way to put real-time send/receive in the browser; for the rationale and how to run it, see [`chat-web/README.md`](./chat-web/README.md).

## License

MIT — see [LICENSE](./LICENSE).
