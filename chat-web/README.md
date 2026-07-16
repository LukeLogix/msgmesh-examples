# chat-web —— MsgMesh 網頁即時聊天室起手式

最小的瀏覽器聊天室:多人連到同一個 topic,一邊發、一邊即時看到所有人的訊息。無前端框架,純 Vite + 原生 JS,方便你直接看懂每一行怎麼用 SDK。

這個樣板**預設走 token-broker**:前端零長期 key,鑑權由一支最小後端(`server.js`)代理。這正是把即時收發放上瀏覽器的正確做法。

- **收**:`@msgmesh/sdk` 的 [`stream()`](https://www.npmjs.com/package/@msgmesh/sdk) —— 瀏覽器原生 SSE(`EventSource`),連 `GET {realtime}/v1/topics/{topic}/sse`。
- **發**:`publish()` —— `POST {gateway}/v1/topics/{topic}/messages`,送出 `{ user, text, ts }` JSON。
- **鑑權**:前端不放 key,改用 SDK 的 `getToken` 向後端 `/api/token` 領短期 token(見下方「token-broker」)。

## token-broker 是什麼

長期 API key 一旦進了瀏覽器 bundle,任何訪客都看得到、也就等於外洩。token-broker 把 key 留在後端,前端只拿短期、降權的 token:

```
瀏覽器 (SDK getToken)
    │  POST /api/token             ← 前端零長期 key
    ▼
server.js (持長期 MSGMESH_API_KEY)
    │  POST {controlPlane}/v1/tokens   Authorization: Bearer <key>
    │  body 降權:{ capabilities:[{ops:[publish,subscribe],topics:[TOPIC]}], ttl_seconds:300 }
    ▼
平台 control-plane  →  回 { token, expires_in }  →  原樣回前端
```

SDK 拿到 token 後會自動快取、於將過期前重取、SSE 重連時換新,所以「5 分鐘 TTL」對使用者是隱形的。平台會把 token 能力收斂成後端 key 的**子集**(只准更窄、逾越回 403),即使 `server.js` 填錯也擴不了權。

## 跑起來

```bash
npm install
cp .env.example .env       # 填入 MSGMESH_API_KEY 等值(見下方「設定」)
npm run build              # Vite 打包前端到 dist/
node --env-file=.env server.js   # 起 token-broker + 服務 dist/,預設 http://localhost:8787
```

打開 http://localhost:8787,輸入暱稱、發一則訊息;另開一個分頁會即時收到。

- `--env-file` 需 **Node ≥ 20.6**。若用 `npm start`(= `node server.js`),它不會自己讀 `.env`,請先自行載入環境變數(如 `export $(grep -v '^#' .env | xargs)`)。
- 改了前端(`src/` / `index.html`)要重跑 `npm run build`;改了 `.env` 或 `server.js` 要重啟 server。

### 開發時要熱更新

想邊改前端邊即時看效果,開兩個終端:

```bash
node --env-file=.env server.js   # 終端 A:token-broker(:8787)
npm run dev                       # 終端 B:Vite dev server(:5173)
```

`vite.config.js` 已把 `/api` 代理到 `:8787`,所以在 http://localhost:5173 開發時,`/api/token` 會轉到後端。(埠不同時設 `PORT` 讓兩邊一致。)

### 需要什麼

- 一個跑著的 MsgMesh(見 repo 根 README 的「共同前置」)。
- 一把能對該 topic **同時 publish 與 subscribe** 的 API key,放進後端 `.env` 的 `MSGMESH_API_KEY`。

## 設定

全部走 `.env`(見 `.env.example`),分兩區。**兩區的 topic 必須一致。**

### 後端(`server.js` 用,絕不進前端 bundle)

| 變數 | 用途 |
| --- | --- |
| `MSGMESH_API_KEY` | 長期 API key(publish + subscribe 能力),用來鑄短期 token。只存後端。 |
| `MSGMESH_CONTROL_PLANE_URL` | 治理面位址(鑄 token 的 `POST /v1/tokens` 打這裡),本機預設 `http://localhost:8080` |
| `MSGMESH_TOPIC` | 聊天室 topic,需與前端 `VITE_MSGMESH_TOPIC` 一致 |
| `PORT` | token-broker 監聽埠,預設 `8787` |

### 前端(`VITE_` 前綴會被打包進 bundle,皆為非敏感值)

| 變數 | 用途 |
| --- | --- |
| `VITE_MSGMESH_GATEWAY_URL` | 收發服務(publish 打這裡) |
| `VITE_MSGMESH_REALTIME_URL` | 即時服務(SSE 串流打這裡) |
| `VITE_MSGMESH_TOPIC` | 聊天室 topic,預設 `chat.lobby` |

## 上線安全

這個樣板**已預設 token-broker**:前端零長期 key,後端鑄短期降權 token —— 這正是上線該有的樣子。實際部署時再留意:

- `.env`(含 `MSGMESH_API_KEY`)只放後端,已被 `.gitignore` 排除,別 commit。
- 讓 `MSGMESH_API_KEY` 的能力就限於這個聊天室 topic 的 publish + subscribe(最小權限);別用 admin 或萬用 key。
- `server.js` 只轉發 `{ token, expires_in }`,不把 key 或上游錯誤細節洩進前端回應。
- 若要做「每人一室」等更細的授權,在 `server.js` 的降權 body 裡按登入身分收窄 `capabilities`(如 `topics:["room.<uid>"]`),token 能力仍是後端 key 的子集。

## 檔案

- `index.html` —— UI 與樣式(單檔,無框架)。
- `src/main.js` —— 讀設定、`getToken` 領 token、`stream()` 收、`publish()` 發、渲染訊息。
- `server.js` —— 最小 token-broker 後端:`POST /api/token` 鑄短期 token + 服務 `dist/` 靜態前端(零額外依賴,純 Node 內建)。
- `vite.config.js` —— 開發期把 `/api` 代理到後端。
- `.env.example` —— 設定範本(複製成 `.env`)。
