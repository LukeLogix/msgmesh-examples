**繁體中文** | [English](./README.en.md)

# agent-notifier —— MsgMesh 事件監看腳本

一個 Node 腳本樣板,體現 MsgMesh 的定位:**給 AI agent 的事件層**。訂閱一個 topic,收到事件就處理 —— 傳統 pub/sub 給人或程式用,這裡讓你把事件流餵給 agent / 後端邏輯。

- **收**:`@msgmesh/sdk` 的 [`subscribe()`](https://www.npmjs.com/package/@msgmesh/sdk) —— 長輪詢迴圈,`GET {gateway}/v1/topics/{topic}/messages`,收到就呼叫你的 handler,回傳停止函式。
- 純 Node,不需 WebSocket;暫時性錯誤 SDK 自動退避重試。

## poll/consume 是 firehose —— 房間(room)在這裡用不了

`subscribe()`(以及底層的 poll / consume)吃的是**整個 topic** 的 firehose:靠 consumer-group offset 消費全部分區、每則各處理一次。它**不做房間(room)過濾**,原因是本質衝突:

- consumer-group 的 offset 是「整個 topic」的進度,per-room 過濾會把別房間的訊息一併吃掉又丟棄,offset 照樣前進 → 漏訊。
- 若「每房一個 group」硬做隔離,等於每個房間都把整個 topic 讀一遍(讀取放大),完全不划算。

因此平台對此類「整 topic 讀」直接把關:**room-scoped 憑證(token 的 `rooms` 非空)呼叫 poll/consume 會被回 403**。這支範例要用**不限房間**的 key(consumer/subscribe 能力、`rooms` 空 = 全房間)——它本來就是要吃整個 topic 的每一則事件。

- **要 per-room 即時處理**(只處理某個房間的事件):走 **realtime**——SSE `stream(topic, …, { room })` 或 WebSocket `streamWs(topic, …, { room })`(見 [`chat-web`](../chat-web))。realtime 是共享的 live-tail,per-room 過濾便宜。
- **後端 worker 要整租戶消費**(把某租戶所有房間的事件都收下來做 DB / 下游):就用**不限房間**的 key(如本範例),一條 `subscribe` 吃整個 topic,自己在 `handleEvent` 裡讀 `msg.key`(= 房間)分流即可。

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
| `MSGMESH_API_KEY` | API key(需 consumer / subscribe 能力,且**不限房間**——poll 吃整個 topic,room-scoped token 會被 403) |
| `MSGMESH_TOPIC` | 要監看的 topic,預設 `orders` |
| `MSGMESH_GROUP` | 消費者 group,預設 `agent-notifier`(同 group 多實例分攤訊息) |

## 改成你的用途

編輯 `index.js` 裡的 `handleEvent(msg)`:`msg.value` 是原始字串(範例會試著 `JSON.parse`)。把 `console.log` 換成寫入 DB、呼叫下游 API、或交給 LLM/agent 決策即可。若你的訊息有帶房間(發佈時的 `key`),`msg.key` 就是房間名,可據以 per-room 分流(poll 收的是全房間 firehose,分流由你在這裡做)。

## 檔案

- `index.js` —— 讀設定、`subscribe()` 監看、處理事件、優雅結束。
- `.env.example` —— 設定範本(複製成 `.env`)。
