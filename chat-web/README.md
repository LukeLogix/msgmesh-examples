# chat-web —— MsgMesh 網頁即時聊天室起手式

最小的瀏覽器聊天室:多人連到同一個 topic,一邊發、一邊即時看到所有人的訊息。無前端框架,純 Vite + 原生 JS,方便你直接看懂每一行怎麼用 SDK。

- **收**:`@msgmesh/sdk` 的 [`stream()`](https://www.npmjs.com/package/@msgmesh/sdk) —— 瀏覽器原生 SSE(`EventSource`),連 `GET {realtime}/v1/topics/{topic}/sse`。
- **發**:`publish()` —— `POST {gateway}/v1/topics/{topic}/messages`,送出 `{ user, text, ts }` JSON。

## 跑起來

```bash
cp .env.example .env      # 填入 gateway / realtime URL 與 API key
npm install
npm run dev               # Vite dev server,預設 http://localhost:5173
```

打開瀏覽器輸入暱稱、發一則訊息;另開一個分頁會即時收到。`npm run build` 產出可部署的靜態檔到 `dist/`。

### 需要什麼

- 一個跑著的 MsgMesh(見 repo 根 README 的「共同前置」)。
- 一把能對該 topic **同時 publish 與 subscribe** 的 API key。

## 設定

全部走 `.env`(見 `.env.example`)。Vite 只注入 `VITE_` 前綴的變數:

| 變數 | 用途 |
| --- | --- |
| `VITE_MSGMESH_GATEWAY_URL` | 收發服務(publish 打這裡) |
| `VITE_MSGMESH_REALTIME_URL` | 即時服務(SSE 串流打這裡) |
| `VITE_MSGMESH_API_KEY` | API key(publish + subscribe 能力) |
| `VITE_MSGMESH_TOPIC` | 聊天室 topic,預設 `chat.lobby` |

## 上線安全(必讀)

這個範例為了「clone 就能跑」,把 API key 透過 `VITE_` 變數打包進前端 —— **它會出現在瀏覽器 bundle 裡,任何訪客都看得到**。這只適合本機或內部 demo。

正式上線改用 **token-broker**,別把長期 key 放進瀏覽器:

1. 後端(持長期 key)開一個小端點,代呼 `POST {controlPlane}/v1/tokens` 換一張短期 dp token 回傳。
2. 前端建構 SDK 時不放 `apiKey`,改給 `getToken`:

   ```js
   const mq = new MsgMesh({
     getToken: async () => (await fetch("/api/mm-token")).then((r) => r.json()), // { token, expires_in }
     gatewayUrl: import.meta.env.VITE_MSGMESH_GATEWAY_URL,
     realtimeUrl: import.meta.env.VITE_MSGMESH_REALTIME_URL,
   });
   ```

   SDK 會自動快取 token、將過期前重取,SSE 重連時也換新。詳見 `@msgmesh/sdk` README 的「瀏覽器/不可信端」段。

## 檔案

- `index.html` —— UI 與樣式(單檔,無框架)。
- `src/main.js` —— 讀設定、`stream()` 收、`publish()` 發、渲染訊息。
- `.env.example` —— 設定範本(複製成 `.env`)。
