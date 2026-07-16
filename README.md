# msgmesh-examples

**MsgMesh** 的官方範例／樣板集合 —— 每個資料夾都是一個「`clone` 就能跑」的最小起手式,示範如何用官方 SDK [`@msgmesh/sdk`](https://www.npmjs.com/package/@msgmesh/sdk) 接入 MsgMesh 這個多租戶事件總線,收發即時事件。

填上你的 gateway / realtime URL 與一把 API key,幾分鐘內就有一個能收發訊息的應用。

## 樣板

| 資料夾 | 是什麼 | 用到的 SDK |
| --- | --- | --- |
| [`chat-web/`](./chat-web) | 瀏覽器即時聊天室(Vite + 原生 JS,無框架) | `stream()` 收(SSE)、`publish()` 發 |
| [`agent-notifier/`](./agent-notifier) | 監看事件的 Node 腳本 —— 給 AI agent / 後端的「事件層」 | `subscribe()` 長輪詢處理每一則事件 |

## 共同前置

1. **一個跑著的 MsgMesh。** 本機最快的方式是跑平台專案 `msgmesh-platform`:
   ```bash
   make up    # 起中間件(Postgres / Redis / Kafka)
   make run   # allinone 跑 host:control-plane :8080 / gateway :8081 / realtime :8082
   ```
   或直接指向你已部署的實例,把各樣板 `.env` 裡的 URL 換成該實例的位址即可。

2. **一把 API key。** 在面板註冊帳號後簽發(明文只顯示一次)。依樣板需要的能力挑 scope:
   - `agent-notifier` 只收訊 → 需 **consumer**(或含 `subscribe` 能力的 key)。
   - `chat-web` 又收又發 → 需一把能同時 **publish + subscribe** 的 key。

3. **Node ≥ 18。** `chat-web` 的建置與 `agent-notifier` 的收發都用 SDK 內建 `fetch`(Node 18+);`agent-notifier` 的 `npm start` 用 `--env-file` 讀 `.env`,需 Node ≥ 20.6(Node 18 的替代跑法見該資料夾 README)。

每個樣板各自附 `README.md`(如何 `npm install && npm run …`)與 `.env.example`。

## 安全須知

- **絕不把 API key commit 進 repo。** 只放在本機 `.env`(已被 `.gitignore` 排除),`.env.example` 只保留佔位值。
- `chat-web` 為求最小可跑,直接把 key 交給瀏覽器,**僅適合本機 / 內部 demo**。瀏覽器裡的東西都會外洩,**正式上線請改用 token-broker**:由後端(持長期 key)代換短期 token,前端改用 SDK 的 `getToken`。作法見 [`chat-web/README.md`](./chat-web/README.md) 的「上線安全」段。

## 授權

MIT —— 見 [LICENSE](./LICENSE)。
