**English** | [繁體中文](./README.zh.md)

# msgmesh-examples

Official examples / starter templates for **MsgMesh** — each folder is a minimal "`clone` and run" starting point that shows how to use the official [`@msgmesh/sdk`](https://www.npmjs.com/package/@msgmesh/sdk) SDK to connect to MsgMesh, the multi-tenant event bus, and send and receive realtime events.

Register in the panel and run its one-click setup: on a newly registered account, keeping its option ticked (the default) also creates the topics the examples use, while an account that already existed, or one where that option was unticked, has to create them itself (see "Common prerequisites"). Put the API key into `.env`, and within minutes you'll have an app that can send and receive messages.

## Templates

| Folder | What it is | SDK used | Room |
| --- | --- | --- | --- |
| [`chat-web/`](./chat-web) | Browser-based realtime chat room (Vite + vanilla JS, no framework) | `stream()` (SSE) / `streamWs()` (WebSocket) to receive, `publish()` to send | ✅ per-room (scoped-down token `rooms` + platform-enforced isolation) |
| [`agent-notifier/`](./agent-notifier) | A Node script that watches events — the "event layer" for AI agents / backends | `subscribe()` long-polling to react to the event stream (at-most-once — see its README) | ⛔ firehose (the whole topic; room-scoped credentials won't work) |

### Which integrations support rooms

A `room` = a sub-channel under a single topic (physically = the Kafka record key). Publish with `publish(topic, body, { room })` to tag a room; **whether you can receive only one room depends on the integration type**:

- **Realtime (SSE `stream` / WebSocket `streamWs`)** supports **per-room**: pass `{ room }` when subscribing to receive only that room; combine it with a backend token-broker that scopes the token's `rooms` down to "the rooms this user may access", and the platform enforces the isolation (403 on overreach). See `chat-web`.
- **Poll / consume (`subscribe` long-polling)** is a **firehose**: it consumes every message of the whole topic with no room filtering; a call with room-scoped credentials is rejected with **403**. For whole-tenant consumption use a key with **no room restriction** and split by reading `msg.room` yourself. See `agent-notifier`.

## Not using JavaScript?

The official examples are JavaScript only for now: the two templates above are all there is. If you work with something else, start here:

- **MCP (Claude Code, Cursor, Claude Desktop).** The MCP server has its own public repo, [`msgmesh-mcp`](https://github.com/LukeLogix/msgmesh-mcp). Its [`examples/mcp-config.example.json`](https://github.com/LukeLogix/msgmesh-mcp/blob/main/examples/mcp-config.example.json) is a config to copy into your MCP client. `MQ_API_KEY` is the only variable you have to set; the three service URLs default to `https://msgmesh-api.alderflux.com`. The config starts the server with `npx`, so the machine still needs Node, but you write no JavaScript. The tools that manage topics, keys and the like need an admin-scope key (the starter key is one); publishing and consuming only need the matching capability on the topic.
- **Python.** `pip install msgmesh` ([PyPI](https://pypi.org/project/msgmesh/)). When you create the client, pass all three service URLs (`control_plane_url`, `gateway_url`, `realtime_url`) as `https://msgmesh-api.alderflux.com`; left out, they default to localhost. The API is synchronous and its names are snake_case. Use the same topics as the examples (`chat.lobby` and `orders`). This repo has no Python example.

## Common prerequisites

1. **A MsgMesh account and the service URL.** Register in the [panel](https://msgmesh-panel.alderflux.com/login?mode=register). The URLs in each template's `.env` (control-plane / gateway / realtime) are all the same address, `https://msgmesh-api.alderflux.com`; `.env.example` already uses it, so keep it when you copy the file.

2. **An API key.** To try the examples on your own machine, the **starter key** from the panel's one-click setup (next item) works for both templates: it has admin scope. Its plaintext is shown only once, so save it right away. If you didn't save it, there is no need to start over: the topics are still there. On the panel's Keys page, choose「key(自訂:可又推又收)」("custom key: can both publish and subscribe"), keep the defaults (publish and subscribe both ticked; the topics field left empty, which means all topics) and press「簽發」("issue"). That key has the capabilities both templates need. Before you put an example into production, issue a narrower key on the panel's Keys page with only the capabilities that template needs:
   - `agent-notifier` only receives → a **consumer** key (or a key that includes the `subscribe` capability).
   - `chat-web` both receives and sends → a key with only **publish + subscribe** on its chat topic (`chat.lobby` by default); see "Production security" in its README.

3. **The topics the examples use: `chat.lobby` (`chat-web`) and `orders` (`agent-notifier`).** The platform does not create topics implicitly; publishing to a topic that doesn't exist returns 404. On a new account, press the one-click setup button on the panel's overview page (labelled「一鍵建立預設 topic + starter key」— the panel is Chinese-only for now) and keep the option「一併建立官方範例用的 topic」("also create the topics the official examples use") ticked, as it is by default. Along with the default topic `events`, that creates `chat.lobby` and `orders`. They count toward your plan's topic quota like any other topic; delete them in the Topics section of the overview page when you no longer need them. Only if your account already existed, or you unticked that option, do you need to create topics with the same names in the Topics section yourself, or point the topic in `.env` at one that exists (for example `events`; in `chat-web` the frontend and backend values must match).

4. **Node ≥ 18 (≥ 20.6 recommended).** Every template's send/receive uses the SDK's built-in `fetch` (Node 18+). The `chat-web` token-broker (`server.js`) and `agent-notifier` both read `.env` via `--env-file`, which needs Node ≥ 20.6 (alternative approaches are in each README).

Each template ships its own `README.md` (how to `npm install && npm run …`) and `.env.example`.

### Panel wording you'll see

The panel's interface is Chinese-only for now. These are the labels a new sign-up meets, in the order they appear:

| Where | On screen | Meaning |
| --- | --- | --- |
| Sign-up form: title and button | 建立帳號 | Create account |
| Sign-up form: button below the form | 使用 Google 登入 | Sign in with Google |
| After you submit the form: card title | 驗證信已寄出 | Verification email sent |
| Same card: subtitle | 開啟信中的連結以完成註冊 | Open the link in the email to finish registering |
| The email: subject | 完成你的 MsgMesh 註冊 | Complete your MsgMesh registration |
| The page the email link opens: title | 完成註冊 | Complete registration |
| Same page: button | 進入面板 → | Enter the panel |
| After the one-click setup: note beside the starter key | 明文僅此一次,請立即保存 | The plaintext is shown this once only; save it now |

## Security notes

- **Never commit an API key into the repo.** Keep it only in a local `.env` (already excluded by `.gitignore`); `.env.example` holds placeholder values only.
- `chat-web` **uses a token-broker by default**: the key lives only in its bundled minimal backend (`server.js`), and the frontend holds no long-lived key — the backend holds the long-lived key and exchanges it for short-lived, scoped-down tokens, which the frontend obtains via the SDK's `getToken`. The scoping also covers **rooms**: the token's `rooms` are narrowed to "the rooms this user may access", enforced by the platform, so different rooms are isolated from one another. This is the correct way to put realtime send/receive in the browser; for the rationale and how to run it, see [`chat-web/README.md`](./chat-web/README.md).

## License

MIT — see [LICENSE](./LICENSE).
