**繁體中文** | [English](./README.en.md)

# chat-web —— MsgMesh 網頁即時聊天室起手式

最小的瀏覽器聊天室:多人連到同一個 topic,一邊發、一邊即時看到所有人的訊息。無前端框架,純 Vite + 原生 JS,方便你直接看懂每一行怎麼用 SDK。

這個樣板**預設走 token-broker**:前端零長期 key,鑑權由一支最小後端(`server.js`)代理。這正是把即時收發放上瀏覽器的正確做法。它同時示範**多房間(room)隔離**與**兩種即時 transport(SSE / WebSocket)**。

- **收**:`@msgmesh/sdk` 的 [`stream()`](https://www.npmjs.com/package/@msgmesh/sdk)(SSE,瀏覽器原生 `EventSource`,連 `GET {realtime}/v1/topics/{topic}/sse`);或 `streamWs()`(WebSocket,同介面)。兩者都可傳選用 `{ room }` 只收某房間。
- **發**:`publish()` —— `POST {gateway}/v1/topics/{topic}/messages`,送出 `{ user, text, ts }` JSON;用 `{ key: room }` 指定房間。
- **鑑權**:前端不放 key,改用 SDK 的 `getToken` 向後端 `/api/token` 領短期 token(見下方「token-broker」)。token 的能力已被後端**降權到該使用者可用的房間**,平台強制(見「多房間與隔離」)。

## token-broker 是什麼

長期 API key 一旦進了瀏覽器 bundle,任何訪客都看得到、也就等於外洩。token-broker 把 key 留在後端,前端只拿短期、降權的 token:

```
瀏覽器 (SDK getToken)
    │  POST /api/token             ← 前端零長期 key
    ▼
server.js (持長期 MSGMESH_API_KEY)
    │  POST {controlPlane}/v1/tokens   Authorization: Bearer <key>
    │  body 降權:{ capabilities:[{ops:[publish,subscribe],topics:[TOPIC],rooms:[<可用房間>]}], ttl_seconds:300 }
    ▼
平台 control-plane  →  回 { token, expires_in }  →  原樣回前端
```

SDK 拿到 token 後會自動快取、於將過期前重取、SSE 重連時換新,所以「5 分鐘 TTL」對使用者是隱形的。平台會把 token 能力收斂成後端 key 的**子集**(只准更窄、逾越回 403),即使 `server.js` 填錯也擴不了權。降權 body 裡的 `rooms` 就是把「這張 token 只能碰哪些房間」寫死進憑證(見下節)。

## 多房間(room)與隔離

`room` = 同一個 topic 底下的子頻道,實體是 **Kafka record key**。發佈時用 key 標記房間、訂閱時用 room 只收該房間;哪些房間可用**由後端鑄的 token 決定並由平台強制**——這是「真隔離」,不靠前端誠實。

資料流(前端房間 → token 降權 → 訂閱/發佈):

```
1. 前端挑房間(網址 ?room= 或點選單) → SDK getToken → POST /api/token
2. server.js 依「這個使用者可用房間」允許集(MSGMESH_ROOMS)鑄 token:
     capabilities:[{ ops:[publish,subscribe], topics:[TOPIC], rooms:[<允許集>] }]
   平台把 token 能力收斂成後端 key 的子集(逾越 403)
3. 前端拿這一張 token:
     訂閱  stream / streamWs(topic, …, { room })   → realtime 只推該房間(?room)
     發佈  publish(topic, body, { key: room })       → 平台以 record key 路由到該房間
4. 平台對每次收 / 發都比對 token 的 rooms:
     ?room / ?key 不在允許集 → 403。前端就算被竄改成別人的房間也拿不到——token 根本沒授權。
```

- **可用房間由後端決定**:前端的 `VITE_MSGMESH_ROOMS` 只用來畫選單;真正的授權邊界是**後端 token 的 `rooms`**(`MSGMESH_ROOMS`)。把 `MSGMESH_ROOMS` 依登入身分產生,就是「每人 / 每租戶一組房間」的多租戶隔離。
- **同一張 token 走遍自己的房間**:token 的 `rooms` 涵蓋使用者「所有可用房間」,所以在允許的房間間切換不必重領 token;切到允許集外才會被擋。
- **不想分房間**:留空 `MSGMESH_ROOMS` 與 `VITE_MSGMESH_ROOMS`,`rooms` 省略 = 不限房間 = 單一大廳,行為同舊版。
- **只有 realtime 能 per-room**:SSE / WS 訂閱可帶 `?room=` 精準收單一房間;但 poll / consume(長輪詢整個 topic)是 **firehose**,room-scoped 憑證用不了(平台回 403)——細顆粒房間請走 realtime。詳見 [`agent-notifier/README.md`](../agent-notifier/README.md)。

> 版本註記:發佈端 `publish(…, { key })` 在 `@msgmesh/sdk` 0.1.3 已支援;**訂閱端 `stream`/`streamWs` 的 `{ room }` 過濾**需與多房間平台一起發布的 SDK 版本(舊版會忽略該參數、收整個 topic)。本樣板隨多房間平台一起上。

## 用 WebSocket 收(streamWs)

預設走 SSE。在網址加 **`?transport=ws`** 就改用 SDK 的 `streamWs`(WebSocket)收訊——介面與 `stream` 一模一樣、同樣吃 `{ room }`:

```js
// SSE(預設)
mq.stream(topic, onMsg, onErr, { room });
// WebSocket:同介面、同 room 過濾,SDK 自管重連
mq.streamWs(topic, onMsg, onErr, { room });
```

適合 SSE 被中間層(proxy / 防火牆)擋掉、或你已有 WebSocket 基礎設施的場景。`streamWs` 用瀏覽器原生 `WebSocket`(所有現代瀏覽器皆內建;Node 端則需 ≥ 22 或改用 `subscribe` 長輪詢)。標題列的 `SSE` / `WS` 徽章會顯示目前用哪一種。

## 跑起來

```bash
npm install
cp .env.example .env       # 填入 MSGMESH_API_KEY 等值(見下方「設定」)
npm run build              # Vite 打包前端到 dist/
node --env-file=.env server.js   # 起 token-broker + 服務 dist/,預設 http://localhost:8787
```

打開 http://localhost:8787,輸入暱稱、發一則訊息;另開一個分頁會即時收到。

- **試多房間**:標題列的 `# lobby / # support / # random` 選單可切房間(等同網址 `?room=support`);兩個分頁在同房間才互看得到,不同房間彼此隔離。
- **試 WebSocket**:網址加 `?transport=ws`(如 `http://localhost:8787/?room=support&transport=ws`)改用 `streamWs` 收訊,徽章會顯示 `WS`。
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

全部走 `.env`(見 `.env.example`),分兩區。**兩區的 topic 與 rooms 需一致。**

### 後端(`server.js` 用,絕不進前端 bundle)

| 變數 | 用途 |
| --- | --- |
| `MSGMESH_API_KEY` | 長期 API key(publish + subscribe 能力,且能收發下方房間),用來鑄短期 token。只存後端。 |
| `MSGMESH_CONTROL_PLANE_URL` | 治理面位址(鑄 token 的 `POST /v1/tokens` 打這裡),本機預設 `http://localhost:8080` |
| `MSGMESH_TOPIC` | 聊天室 topic,需與前端 `VITE_MSGMESH_TOPIC` 一致 |
| `MSGMESH_ROOMS` | 這個使用者「可用房間」允許集(逗號分隔),鑄 token 時降權到這一集(**真正的授權邊界**)。留空=不限房間 |
| `PORT` | token-broker 監聽埠,預設 `8787` |

### 前端(`VITE_` 前綴會被打包進 bundle,皆為非敏感值)

| 變數 | 用途 |
| --- | --- |
| `VITE_MSGMESH_GATEWAY_URL` | 收發服務(publish 打這裡) |
| `VITE_MSGMESH_REALTIME_URL` | 即時服務(SSE 串流與 WebSocket 都打這裡) |
| `VITE_MSGMESH_TOPIC` | 聊天室 topic,預設 `chat.lobby` |
| `VITE_MSGMESH_ROOMS` | 房間選單清單(逗號分隔),**僅前端 UI 用**,需與後端 `MSGMESH_ROOMS` 一致。留空=單一大廳 |

## 上線安全

這個樣板**已預設 token-broker**:前端零長期 key,後端鑄短期降權 token —— 這正是上線該有的樣子。實際部署時再留意:

- `.env`(含 `MSGMESH_API_KEY`)只放後端,已被 `.gitignore` 排除,別 commit。
- 讓 `MSGMESH_API_KEY` 的能力就限於這個聊天室 topic 的 publish + subscribe(最小權限);別用 admin 或萬用 key。
- `server.js` 只轉發 `{ token, expires_in }`,不把 key 或上游錯誤細節洩進前端回應。
- 「每人一組房間」就是把 `MSGMESH_ROOMS` 改成**依登入身分動態產生**(如某租戶的房間集),在 `server.js` 的降權 body 填進 `capabilities[].rooms`——token 只能碰這些房間,平台強制,其餘一律 403。這比「每房一個 topic」更省(共用一個 topic + 一條 live-tail),隔離仍由憑證保證。
- **平台不驗「誰在說話」。** 房間隔離只保證「能收發哪些房間」,不驗證訊息裡的 `user`(發訊者)——這個 demo 的暱稱就是前端自報的,同一房內任何人都能把 `user` 填成別人**冒名發言**。正式聊天要防冒名:**在 `server.js` 鑄 token 時綁定該登入使用者,並由後端戳上 / 驗證 `user`**,別讓前端自報身分。

## 檔案

- `index.html` —— UI 與樣式(單檔,無框架;含房間選單與 SSE/WS 徽章)。
- `src/main.js` —— 讀設定、`getToken` 領 token、`stream()`/`streamWs()` 收(帶 `room`)、`publish()` 發(帶 `key`)、房間切換、渲染訊息。
- `server.js` —— 最小 token-broker 後端:`POST /api/token` 鑄短期**房間降權** token + 服務 `dist/` 靜態前端(零額外依賴,純 Node 內建)。
- `vite.config.js` —— 開發期把 `/api` 代理到後端。
- `.env.example` —— 設定範本(複製成 `.env`)。
