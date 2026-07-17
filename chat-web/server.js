// server.js —— chat-web 的最小 token-broker 後端(零額外依賴,純 Node 內建 http + fetch)。
//
// 它做兩件事:
//   1. POST /api/token —— 用「伺服器端長期 key」向平台換一張「短期、降權」的資料面 token,
//      原樣回給前端。長期 key 只存在這支後端,永不進瀏覽器。
//   2. 服務 dist/ 靜態前端(Vite build 產物),SPA fallback 回 index.html。
//
// 這正是這個樣板要教的最佳實踐:前端零長期 key,後端鑄短期 token。
//
// 多房間(room)隔離:一個 topic 底下用「房間」切分(room = Kafka record key)。若設了
// MSGMESH_ROOMS,鑄 token 時把 capabilities 的 rooms 降權到「這個使用者可用的房間集」——
// token 只能對這些房間 publish(?key)/subscribe(?room),逾越由平台回 403(真隔離,不靠前端誠實)。
// 跑法:先 `npm run build` 產出 dist/,再 `node --env-file=.env server.js`(Node ≥ 20.6)。

import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join, normalize, extname, sep } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const DIST = join(HERE, "dist");

// 伺服器端設定(絕不進前端)。CONTROL_PLANE 是治理面,鑄 token 的端點在這。
const API_KEY = process.env.MSGMESH_API_KEY;
const CONTROL_PLANE = (process.env.MSGMESH_CONTROL_PLANE_URL || "http://localhost:8080").replace(/\/$/, "");
const TOPIC = process.env.MSGMESH_TOPIC || "chat.lobby";
const PORT = Number(process.env.PORT) || 8787;

// ROOMS —— 這個 broker 代表的使用者「可用房間」允許集(逗號分隔;真實 app 會依登入身分決定)。
// 鑄 token 時把 capabilities 的 rooms 降權到這一集:token 只能對這些房間收發,逾越回 403。
// 空/未設 = 省略 rooms = 不限房間(向後相容,單一大廳,行為同舊版)。
const ROOMS = (process.env.MSGMESH_ROOMS || "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

// 降權範本:簽出的 token 只准對「這一個 topic」publish+subscribe,TTL 5 分鐘;若設了 ROOMS,
// 再把能力的 rooms 收窄到該集(房間隔離)。平台會把它收斂成呼叫者 key 能力的子集(逾越回 403),
// 故這裡填什麼都不會擴權——長期 key 須本身能收發該 topic 全部房間(rooms 空=不限),才鑄得出。
const TOKEN_TTL_SECONDS = 300;
const tokenRequestBody = () => {
  const rule = { ops: ["publish", "subscribe"], topics: [TOPIC] };
  // 有設 ROOMS 才附 rooms(把 token 降權到這些房間);未設則省略=不限房間。
  if (ROOMS.length) rule.rooms = ROOMS;
  return JSON.stringify({ capabilities: [rule], ttl_seconds: TOKEN_TTL_SECONDS });
};

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".map": "application/json; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
};

function sendJSON(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(body);
}

// mintToken 代呼平台 POST /v1/tokens,把 {token, expires_in} 原樣回給前端。
// 任何失敗都回通用訊息 + 記在伺服器端,絕不把長期 key 或上游 body 洩進前端回應。
async function mintToken(res) {
  if (!API_KEY || API_KEY === "replace-me") {
    console.error("[token-broker] 未設定 MSGMESH_API_KEY —— 無法鑄 token(請填 .env)");
    return sendJSON(res, 500, { error: "token broker 未設定" });
  }

  let upstream;
  try {
    upstream = await fetch(`${CONTROL_PLANE}/v1/tokens`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${API_KEY}`,
        "content-type": "application/json",
      },
      body: tokenRequestBody(),
    });
  } catch (err) {
    // 連不上 control plane(位址錯 / 服務沒起 / 網路)——回 502,細節只記後端。
    console.error("[token-broker] 連線 control plane 失敗:", err?.message || err);
    return sendJSON(res, 502, { error: "token broker: 無法連線到 control plane" });
  }

  if (!upstream.ok) {
    // 上游回非 2xx(key 無效 / 能力不足 / TTL 逾限…)——對前端這是後端設定問題,回 502。
    // 只在伺服器端記狀態碼與 body 供排障;不把上游 body 轉發前端(避免洩漏設定細節)。
    const detail = await upstream.text().catch(() => "");
    console.error(`[token-broker] control plane 回應 ${upstream.status}: ${detail}`);
    return sendJSON(res, 502, { error: `token broker: control plane 回應錯誤 (${upstream.status})` });
  }

  let data;
  try {
    data = await upstream.json();
  } catch {
    console.error("[token-broker] control plane 回應非 JSON");
    return sendJSON(res, 502, { error: "token broker: control plane 回應格式錯誤" });
  }

  // SDK 的 getToken 只需要 { token, expires_in };只轉發這兩個欄位。
  return sendJSON(res, 200, { token: data.token, expires_in: data.expires_in });
}

// serveStatic 從 dist/ 提供靜態檔;找不到就 SPA fallback 回 index.html。
async function serveStatic(req, res) {
  // 只允許 GET/HEAD 取靜態資源。
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405, { allow: "GET, HEAD" });
    return res.end();
  }

  // 正規化路徑並擋目錄穿越:解析後必須仍落在 dist/ 內。
  const urlPath = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
  let filePath = normalize(join(DIST, urlPath));
  if (filePath !== DIST && !filePath.startsWith(DIST + sep)) {
    res.writeHead(403);
    return res.end("forbidden");
  }
  if (urlPath.endsWith("/")) filePath = join(filePath, "index.html");

  try {
    const body = await readFile(filePath);
    const type = MIME[extname(filePath).toLowerCase()] || "application/octet-stream";
    res.writeHead(200, { "content-type": type });
    return res.end(req.method === "HEAD" ? undefined : body);
  } catch {
    // 找不到檔:單頁應用一律回 index.html(SPA fallback)。
    try {
      const index = await readFile(join(DIST, "index.html"));
      res.writeHead(200, { "content-type": MIME[".html"] });
      return res.end(req.method === "HEAD" ? undefined : index);
    } catch {
      // 連 index.html 都沒有——多半是還沒 build。
      res.writeHead(404, { "content-type": MIME[".txt"] });
      return res.end("尚未建置:請先執行 `npm run build` 產出 dist/,再啟動 server。");
    }
  }
}

const server = createServer((req, res) => {
  const { pathname } = new URL(req.url, "http://localhost");

  if (pathname === "/api/token") {
    if (req.method !== "POST") {
      res.writeHead(405, { allow: "POST" });
      return res.end();
    }
    req.resume(); // 前端不帶 body,但仍把請求流排掉,避免連線卡住
    return void mintToken(res);
  }

  return void serveStatic(req, res);
});

server.listen(PORT, () => {
  console.log(`chat-web token-broker 已啟動 → http://localhost:${PORT}`);
  console.log(`  control plane: ${CONTROL_PLANE}`);
  console.log(`  topic:         ${TOPIC}`);
  console.log(`  rooms:         ${ROOMS.length ? ROOMS.join(", ") : "(不限房間;未設 MSGMESH_ROOMS)"}`);
  console.log(`  靜態來源:      ${DIST}`);
  if (!API_KEY || API_KEY === "replace-me") {
    console.warn("  ⚠ 尚未設定 MSGMESH_API_KEY —— /api/token 會回 500,請填 .env 後重啟。");
  }
});
