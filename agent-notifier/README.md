# agent-notifier —— MsgMesh 事件監看腳本

一個 Node 腳本樣板,體現 MsgMesh 的定位:**給 AI agent 的事件層**。訂閱一個 topic,收到事件就處理 —— 傳統 pub/sub 給人或程式用,這裡讓你把事件流餵給 agent / 後端邏輯。

- **收**:`@msgmesh/sdk` 的 [`subscribe()`](https://www.npmjs.com/package/@msgmesh/sdk) —— 長輪詢迴圈,`GET {gateway}/v1/topics/{topic}/messages`,收到就呼叫你的 handler,回傳停止函式。
- 純 Node,不需 WebSocket;暫時性錯誤 SDK 自動退避重試。

## 跑起來

```bash
cp .env.example .env      # 填入 gateway URL 與 consumer API key
npm install
npm start                 # = node --env-file=.env index.js
```

啟動後會印一行「訂閱 topic …」,接著每收到一則事件就印出來。往該 topic publish 一筆(用 `chat-web`、SDK、或 `curl`)就會看到它跳出來。`Ctrl-C` 優雅結束。

### Node 18 跑法

`npm start` 用的 `--env-file` 需 Node ≥ 20.6。若你在 Node 18,改成自己載入環境變數:

```bash
export $(grep -v '^#' .env | xargs) && node index.js
```

## 設定

| 變數 | 用途 |
| --- | --- |
| `MSGMESH_GATEWAY_URL` | 收發服務位址 |
| `MSGMESH_API_KEY` | API key(需 consumer / subscribe 能力) |
| `MSGMESH_TOPIC` | 要監看的 topic,預設 `orders` |
| `MSGMESH_GROUP` | 消費者 group,預設 `agent-notifier`(同 group 多實例分攤訊息) |

## 改成你的用途

編輯 `index.js` 裡的 `handleEvent(msg)`:`msg.value` 是原始字串(範例會試著 `JSON.parse`)。把 `console.log` 換成寫入 DB、呼叫下游 API、或交給 LLM/agent 決策即可。

## 檔案

- `index.js` —— 讀設定、`subscribe()` 監看、處理事件、優雅結束。
- `.env.example` —— 設定範本(複製成 `.env`)。
