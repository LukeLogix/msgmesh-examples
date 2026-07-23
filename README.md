**繁體中文** | [English](./README.en.md)

# msgmesh-examples

**MsgMesh** 的官方範例／樣板集合 —— 每個資料夾都是一個「`clone` 就能跑」的最小起手式,示範如何用官方 SDK [`@msgmesh/sdk`](https://www.npmjs.com/package/@msgmesh/sdk) 接入 MsgMesh 這個多租戶事件總線,收發即時事件。

填上你的 gateway / realtime URL 與一把 API key,幾分鐘內就有一個能收發訊息的應用。

## 樣板

| 資料夾 | 是什麼 | 用到的 SDK | 房間(room) |
| --- | --- | --- | --- |
| [`chat-web/`](./chat-web) | 瀏覽器即時聊天室(Vite + 原生 JS,無框架) | `stream()`(SSE)/ `streamWs()`(WebSocket)收、`publish()` 發 | ✅ per-room(token 降權 `rooms` + 平台強制隔離) |
| [`agent-notifier/`](./agent-notifier) | 監看事件的 Node 腳本 —— 給 AI agent / 後端的「事件層」 | `subscribe()` 長輪詢處理每一則事件 | ⛔ firehose(整個 topic;room-scoped 憑證用不了) |

### 房間(room)適用於哪些接入

`room` = 同一個 topic 底下的子頻道(實體 = Kafka record key)。發佈用 `publish(topic, body, { key: room })` 標記房間;**能不能只收某房間,取決於接入類型**:

- **Realtime(SSE `stream` / WebSocket `streamWs`)** 可 **per-room**:訂閱傳 `{ room }` 只收該房間;搭配後端 token-broker 把 token 的 `rooms` 降權到「該使用者可用房間」,平台強制隔離(逾越 403)。見 `chat-web`。
- **Poll / consume(`subscribe` 長輪詢)** 是 **firehose**:吃整個 topic 的每一則,不做房間過濾;room-scoped 憑證呼叫會被 **403**。整租戶消費請用**不限房間**的 key,自行讀 `msg.key` 分流。見 `agent-notifier`。

## 共同前置

1. **一個跑著的 MsgMesh 實例。** 把各樣板 `.env` 裡的 gateway / realtime / control-plane URL 指向你的實例——你**自架**的,或你 **hosted 帳號**的位址(在面板註冊即可拿到,見下）。本機自架時各服務預設埠為 control-plane `:8080` / gateway `:8081` / realtime `:8082`。

2. **一把 API key。** 在面板註冊帳號後簽發(明文只顯示一次)。依樣板需要的能力挑 scope:
   - `agent-notifier` 只收訊 → 需 **consumer**(或含 `subscribe` 能力的 key)。
   - `chat-web` 又收又發 → 需一把能同時 **publish + subscribe** 的 key。

3. **Node ≥ 18(建議 ≥ 20.6)。** 各樣板的收發都用 SDK 內建 `fetch`(Node 18+)。`chat-web` 的 token-broker(`server.js`)與 `agent-notifier` 都用 `--env-file` 讀 `.env`,需 Node ≥ 20.6(替代跑法見各自 README)。

每個樣板各自附 `README.md`(如何 `npm install && npm run …`)與 `.env.example`。

## 安全須知

- **絕不把 API key commit 進 repo。** 只放在本機 `.env`(已被 `.gitignore` 排除),`.env.example` 只保留佔位值。
- `chat-web` **預設走 token-broker**:key 只放在它自帶的最小後端(`server.js`),前端零長期 key —— 後端持長期 key 代換短期降權 token,前端用 SDK 的 `getToken` 領取。降權也涵蓋**房間**:token 的 `rooms` 被收窄到「該使用者可用房間」,平台強制,不同房間彼此隔離。這正是把即時收發放上瀏覽器的正確做法,原理與跑法見 [`chat-web/README.md`](./chat-web/README.md)。

## 授權

MIT —— 見 [LICENSE](./LICENSE)。
