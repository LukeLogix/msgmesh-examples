[English](./README.md) | **繁體中文**

# msgmesh-examples

**MsgMesh** 的官方範例／樣板集合 —— 每個資料夾都是一個「`clone` 就能跑」的最小起手式,示範如何用官方 SDK [`@msgmesh/sdk`](https://www.npmjs.com/package/@msgmesh/sdk) 接入 MsgMesh 這個多租戶事件總線,收發即時事件。

在面板註冊並按一鍵開箱:新註冊的帳號維持預設勾選,就會一併建好範例要用的 topic;既有帳號、或當時沒勾選的人,則要自行建立(見「共同前置」)。再把 API key 填進 `.env`,幾分鐘內就有一個能收發訊息的應用。

## 樣板

| 資料夾 | 是什麼 | 用到的 SDK | 房間(room) |
| --- | --- | --- | --- |
| [`chat-web/`](./chat-web) | 瀏覽器即時聊天室(Vite + 原生 JS,無框架) | `stream()`(SSE)/ `streamWs()`(WebSocket)收、`publish()` 發 | ✅ per-room(token 降權 `rooms` + 平台強制隔離) |
| [`agent-notifier/`](./agent-notifier) | 監看事件的 Node 腳本 —— 給 AI agent / 後端的「事件層」 | `subscribe()` 長輪詢對事件流做出反應(at-most-once,見其 README) | ⛔ firehose(整個 topic;room-scoped 憑證用不了) |

### 房間(room)適用於哪些接入

`room` = 同一個 topic 底下的子頻道(實體 = Kafka record key)。發佈用 `publish(topic, body, { room })` 標記房間;**能不能只收某房間,取決於接入類型**:

- **Realtime(SSE `stream` / WebSocket `streamWs`)** 可 **per-room**:訂閱傳 `{ room }` 只收該房間;搭配後端 token-broker 把 token 的 `rooms` 降權到「該使用者可用房間」,平台強制隔離(逾越 403)。見 `chat-web`。
- **Poll / consume(`subscribe` 長輪詢)** 是 **firehose**:吃整個 topic(不分房間)的事件流,不做房間過濾;room-scoped 憑證呼叫會被 **403**。整租戶消費請用**不限房間**的 key,自行讀 `msg.room` 分流。見 `agent-notifier`。

## 不用 JavaScript?

目前官方範例只有 JavaScript:上面兩個樣板就是全部。用別的工具接入,可以從下面兩種開始。不管用哪一種,都還是需要帳號、API key 與 topic:見下方「共同前置」第 1–3 項。

- **MCP(Claude Code、Cursor、Claude Desktop)。** MCP server 的安裝說明與設定範例放在公開 repo [`msgmesh-mcp`](https://github.com/LukeLogix/msgmesh-mcp)。其中的 [`examples/mcp-config.example.json`](https://github.com/LukeLogix/msgmesh-mcp/blob/main/examples/mcp-config.example.json) 是給 MCP client 用的設定,複製過去後要把 `MQ_API_KEY` 的佔位字串換成自己的 key。必填的環境變數只有 `MQ_API_KEY`;三個服務網址預設就是 `https://msgmesh-api.alderflux.com`。這份設定用 `npx` 啟動 server,所以電腦上仍要有 Node,但不必寫 JavaScript。管理 topic、key 這類的 tool 需要 admin 權限的 key(starter key 就是);收發只需要該 topic 對應的能力。
- **Python。** `pip install msgmesh`([PyPI](https://pypi.org/project/msgmesh/))。建立 client 時,三個服務網址(`control_plane_url`、`gateway_url`、`realtime_url`)都傳 `https://msgmesh-api.alderflux.com`;不傳的話預設是 localhost。API 是同步的,方法命名用 snake_case。一鍵開箱建好的 topic(`chat.lobby`、`orders`)在 Python 一樣可用。這個 repo 沒有 Python 範例。

## 共同前置

1. **MsgMesh 帳號與服務網址。** 在[面板](https://msgmesh-panel.alderflux.com/login?mode=register)註冊帳號。各樣板 `.env` 裡的 control-plane / gateway / realtime 網址都是同一個位址 `https://msgmesh-api.alderflux.com`;`.env.example` 已經填好,複製後維持原值即可。

2. **一把 API key。** 在自己電腦上試跑,可以直接用一鍵開箱(見下一項)給的 **starter key**:它是 admin 權限,兩個樣板都能用。明文只顯示一次,請當下保存。

   沒存到也不必重來:topic 都還在,到面板的 Keys 頁選「key(自訂:可又推又收)」,維持預設(publish + subscribe 都勾、topics 留空 = 所有 topic)直接按「簽發」,這把 key 就具備兩個樣板需要的能力。

   範例要上線前,改到面板的 Keys 頁另簽一把只給該樣板所需能力的 key:
   - `agent-notifier` 只收訊 → **consumer**(或含 `subscribe` 能力的 key)。
   - `chat-web` 又收又發 → 只對它的聊天室 topic(預設 `chat.lobby`)有 **publish + subscribe** 能力的 key,見其 README「上線安全」。

3. **範例要用的 topic:`chat.lobby`(`chat-web`)與 `orders`(`agent-notifier`)。** 平台不會自動建立 topic,發到不存在的 topic 會回 404。新帳號在面板總覽按「一鍵建立預設 topic + starter key」,並維持預設勾選「一併建立官方範例用的 topic」,除了預設 topic `events`,也會建好 `chat.lobby` 與 `orders`。它們和其他 topic 一樣佔方案的 topic 額度,不用時可在總覽的 Topics 區塊刪除。既有帳號、或當時沒勾這個選項的人,才需要自己在 Topics 區塊建立同名 topic,或把 `.env` 的 topic 改成已存在的(例如 `events`;`chat-web` 的前後端兩處要一致)。

4. **Node ≥ 18(建議 ≥ 20.6)。** 各樣板的收發都用 SDK 內建 `fetch`(Node 18+)。`chat-web` 的 token-broker(`server.js`)與 `agent-notifier` 都用 `--env-file` 讀 `.env`,需 Node ≥ 20.6(替代跑法見各自 README)。

每個樣板各自附 `README.md`(如何 `npm install && npm run …`)與 `.env.example`。

## 安全須知

- **絕不把 API key commit 進 repo。** 只放在本機 `.env`(已被 `.gitignore` 排除),`.env.example` 只保留佔位值。
- `chat-web` **預設走 token-broker**:key 只放在它自帶的最小後端(`server.js`),前端零長期 key —— 後端持長期 key 代換短期降權 token,前端用 SDK 的 `getToken` 領取。降權也涵蓋**房間**:token 的 `rooms` 被收窄到「該使用者可用房間」,平台強制,不同房間彼此隔離。這正是把即時收發放上瀏覽器的正確做法,原理與跑法見 [`chat-web/README.zh.md`](./chat-web/README.zh.md)。

## 授權

MIT —— 見 [LICENSE](./LICENSE)。
