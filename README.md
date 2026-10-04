**English** | [繁體中文](./README.zh.md)

# msgmesh-examples

Official examples / starter templates for **MsgMesh** — each folder is a minimal "`clone` and run" starting point that shows how to use the official [`@msgmesh/sdk`](https://www.npmjs.com/package/@msgmesh/sdk) SDK to connect to MsgMesh, the multi-tenant event bus, and send and receive realtime events.

Fill in an API key and the service URLs, create the topic the example uses, and within minutes you'll have an app that can send and receive messages.

## Templates

| Folder | What it is | SDK used | Room |
| --- | --- | --- | --- |
| [`chat-web/`](./chat-web) | Browser-based realtime chat room (Vite + vanilla JS, no framework) | `stream()` (SSE) / `streamWs()` (WebSocket) to receive, `publish()` to send | ✅ per-room (scoped-down token `rooms` + platform-enforced isolation) |
| [`agent-notifier/`](./agent-notifier) | A Node script that watches events — the "event layer" for AI agents / backends | `subscribe()` long-polling to react to the event stream (at-most-once — see its README) | ⛔ firehose (the whole topic; room-scoped credentials won't work) |

### Which integrations support rooms

A `room` = a sub-channel under a single topic (physically = the Kafka record key). Publish with `publish(topic, body, { room })` to tag a room; **whether you can receive only one room depends on the integration type**:

- **Realtime (SSE `stream` / WebSocket `streamWs`)** supports **per-room**: pass `{ room }` when subscribing to receive only that room; combine it with a backend token-broker that scopes the token's `rooms` down to "the rooms this user may access", and the platform enforces the isolation (403 on overreach). See `chat-web`.
- **Poll / consume (`subscribe` long-polling)** is a **firehose**: it consumes every message of the whole topic with no room filtering; a call with room-scoped credentials is rejected with **403**. For whole-tenant consumption use a key with **no room restriction** and split by reading `msg.room` yourself. See `agent-notifier`.

## Common prerequisites

1. **A MsgMesh account and the service URLs.** Register in the [panel](https://msgmesh-panel.alderflux.com). Set all three URLs in each template's `.env` (control-plane / gateway / realtime) to `https://msgmesh-api.alderflux.com` — the defaults in `.env.example` point at `localhost`, which won't reach MsgMesh, so you must change them.

2. **An API key.** Issued after registering an account in the panel (the plaintext is shown only once). Pick the scope by the capabilities each template needs:
   - `agent-notifier` only receives → needs a **consumer** key (or a key that includes the `subscribe` capability).
   - `chat-web` both receives and sends → needs a key that can both **publish + subscribe**.

3. **Create the topic the example uses first.** The platform does not create topics implicitly; publishing to a topic that doesn't exist returns 404. The panel's one-click starter button (labelled「一鍵建立預設 topic + starter key」— the panel is Chinese-only for now) only creates `events`, while the examples default to `chat.lobby` (`chat-web`) and `orders` (`agent-notifier`). Create a topic with the same name in the panel, or point the topic in `.env` at one that exists (for example `events`; in `chat-web` the frontend and backend values must match).

4. **Node ≥ 18 (≥ 20.6 recommended).** Every template's send/receive uses the SDK's built-in `fetch` (Node 18+). The `chat-web` token-broker (`server.js`) and `agent-notifier` both read `.env` via `--env-file`, which needs Node ≥ 20.6 (alternative approaches are in each README).

Each template ships its own `README.md` (how to `npm install && npm run …`) and `.env.example`.

## Security notes

- **Never commit an API key into the repo.** Keep it only in a local `.env` (already excluded by `.gitignore`); `.env.example` holds placeholder values only.
- `chat-web` **uses a token-broker by default**: the key lives only in its bundled minimal backend (`server.js`), and the frontend holds no long-lived key — the backend holds the long-lived key and exchanges it for short-lived, scoped-down tokens, which the frontend obtains via the SDK's `getToken`. The scoping also covers **rooms**: the token's `rooms` are narrowed to "the rooms this user may access", enforced by the platform, so different rooms are isolated from one another. This is the correct way to put realtime send/receive in the browser; for the rationale and how to run it, see [`chat-web/README.md`](./chat-web/README.md).

## License

MIT — see [LICENSE](./LICENSE).
