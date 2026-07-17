// chat-web —— 最小網頁聊天室:用 @msgmesh/sdk 的 stream()(SSE)即時收訊、publish() 發訊。
// 鑑權走 token-broker:前端零長期 key,改由後端(server.js)的 /api/token 鑄短期降權 token。
// gateway / realtime URL 與 topic 屬非敏感,續由 Vite 注入(見 .env.example)。
//
// 多房間(room):一個 topic 底下用「房間」切分。發佈時用 publish 的 key 指定房間(?key),
// 訂閱時傳 room 只收該房間(?room)。哪些房間可用由「後端鑄的 token 的 rooms」決定並由平台強制
// (逾越回 403);前端這份 VITE_MSGMESH_ROOMS 只用來畫房間選單,不是授權邊界。
//
// transport:預設走 SSE(stream)。網址加 ?transport=ws 改用 WebSocket(streamWs),介面相同、
// 同樣支援 room。用來示範「ws 也能收 room」的替代路徑。
import { MsgMesh } from "@msgmesh/sdk";

const env = import.meta.env;
const cfg = {
  gatewayUrl: env.VITE_MSGMESH_GATEWAY_URL,
  realtimeUrl: env.VITE_MSGMESH_REALTIME_URL,
  topic: env.VITE_MSGMESH_TOPIC || "chat.lobby",
  // 可選單的房間清單(僅前端 UI 用;需與後端 MSGMESH_ROOMS 一致)。空=單一大廳、不顯示選單。
  rooms: (env.VITE_MSGMESH_ROOMS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean),
};

// 從網址讀「目前房間」與「transport」。room 不在允許清單(或沒清單)時退回第一個房間 / 無房間。
const params = new URLSearchParams(location.search);
const urlRoom = params.get("room");
let activeRoom =
  urlRoom && (cfg.rooms.length === 0 || cfg.rooms.includes(urlRoom))
    ? urlRoom
    : cfg.rooms[0] || "";
let useWs = params.get("transport") === "ws";

// 向後端 token-broker 領一張短期資料面 token。SDK 會自動快取、將過期前重取、重連時換新,
// 故這裡不需自己管理有效期。回傳需為 { token, expires_in }。這張 token 的 rooms 已由後端降權,
// 涵蓋此使用者「所有可用房間」,所以同一張就能在允許的房間間切換,不必每次換房重領。
async function getToken() {
  const r = await fetch("/api/token", { method: "POST" });
  if (!r.ok) throw new Error("token broker " + r.status);
  return r.json();
}

const $ = (id) => document.getElementById(id);
const messagesEl = $("messages");
const form = $("composer");
const textInput = $("text");
const nameInput = $("name");
const statusEl = $("status");
const roomsEl = $("rooms");
const transportEl = $("transport");
const sendBtn = form.querySelector("button");

// 每個分頁一個隨機暱稱,方便區分「自己」與別人的訊息。
nameInput.value = "guest-" + Math.random().toString(36).slice(2, 6);

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.dataset.kind = kind || "";
}

function addMessage({ user, text, ts }, mine) {
  const li = document.createElement("li");
  li.className = "msg" + (mine ? " mine" : "");

  const who = document.createElement("span");
  who.className = "who";
  who.textContent = user || "anon";

  const body = document.createElement("span");
  body.className = "body";
  body.textContent = text ?? "";

  const time = document.createElement("time");
  time.textContent = new Date(ts || Date.now()).toLocaleTimeString();

  li.append(who, body, time);
  messagesEl.append(li);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// 畫房間選單(僅在有設 VITE_MSGMESH_ROOMS 時)。點選=切到該房間。
function renderRooms() {
  roomsEl.textContent = "";
  if (cfg.rooms.length === 0) return;
  for (const room of cfg.rooms) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "room-btn" + (room === activeRoom ? " active" : "");
    btn.textContent = "# " + room;
    btn.addEventListener("click", () => switchRoom(room));
    roomsEl.append(btn);
  }
}

// 顯示目前 transport(SSE / WS)徽章。
function renderTransport() {
  transportEl.textContent = useWs ? "WS" : "SSE";
  transportEl.title = useWs
    ? "WebSocket(streamWs);網址去掉 ?transport=ws 可切回 SSE"
    : "Server-Sent Events(stream);網址加 ?transport=ws 可改用 WebSocket";
}

// URL 設定不齊全時直接在畫面提示,不硬連線(避免一堆 console 錯誤看不懂)。
// token 由後端 /api/token 供應,前端無從得知 key;token-broker 是否就緒由 SDK 呼叫時回報。
if (!cfg.gatewayUrl || !cfg.realtimeUrl) {
  setStatus("尚未設定:請複製 .env.example 成 .env,填入 gateway/realtime URL,再重新 build。", "error");
  sendBtn.disabled = true;
} else {
  start();
}

let mq;
let stopStream = null; // 目前訂閱的停止函式(切換房間 / transport 時先停舊的)

function start() {
  mq = new MsgMesh({
    getToken,
    gatewayUrl: cfg.gatewayUrl,
    realtimeUrl: cfg.realtimeUrl,
  });

  // 選了 WS 卻裝到不含 streamWs 的舊版 SDK:退回 SSE 並提示,不讓範例整個掛掉。
  if (useWs && typeof mq.streamWs !== "function") {
    console.warn("此版 @msgmesh/sdk 無 streamWs,退回 SSE。請升級 SDK 以使用 WebSocket transport。");
    useWs = false;
  }

  renderTransport();
  renderRooms();
  subscribe();

  // 發:publish JSON 物件,並用 key 指定房間(平台以 record key 做房間路由,且對照 token 的 rooms
  // 強制授權——不在允許集回 403)。訊息會經訂閱回流,由 onMessage 統一渲染(含自己這筆)。
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = textInput.value.trim();
    if (!text) return;
    const user = nameInput.value.trim() || "anon";
    textInput.value = "";
    try {
      const opts = activeRoom ? { key: activeRoom } : {};
      await mq.publish(cfg.topic, { user, text, ts: Date.now() }, opts);
    } catch (err) {
      console.error("publish 失敗:", err);
      setStatus("送出失敗:" + (err?.message || err), "error");
      textInput.value = text; // 還原內容,方便重送
    }
  });
}

// subscribe 依目前 transport 與 activeRoom 開一條即時訂閱,回收上一條(若有)。
// stream / streamWs 介面一致,第四參數傳 { room } 只收該房間;省略=收該 topic 全部訊息。
function subscribe() {
  stopStream?.();

  const onMessage = (data) => {
    // 回呼收到的是「訊息 value 字串」——我們發的是 JSON,故先 parse。
    let payload;
    try {
      payload = JSON.parse(data);
    } catch {
      payload = { text: data };
    }
    addMessage(payload, payload.user === nameInput.value.trim());
  };
  const onError = (err) => {
    console.error("stream 錯誤:", err);
    // room-scoped token 訂閱不在允許集的房間會被平台擋(403);其餘多為暫時性斷線,SDK 會自動重連。
    setStatus("連線中斷或房間不被授權,SDK 會自動重連(詳見 console)。", "error");
  };
  const opts = activeRoom ? { room: activeRoom } : undefined;

  // stream()/streamWs() 回傳停止函式;整頁存活時不需主動停止,但切房 / 切 transport 要先停舊訂閱。
  stopStream = useWs
    ? mq.streamWs(cfg.topic, onMessage, onError, opts)
    : mq.stream(cfg.topic, onMessage, onError, opts);

  // SSE/WS 都沒有暴露「已就緒且必有訊息」的明確時點,先樂觀標示就緒;真斷線時 onError 會覆蓋。
  const where = activeRoom ? `${cfg.topic} · #${activeRoom}` : cfg.topic;
  setStatus(`已連線(${useWs ? "WS" : "SSE"}) · ${where}(等待訊息)`, "ok");
}

// switchRoom 在允許的房間間切換:更新網址(可分享)、清畫面、用同一張 token 重新訂閱與發佈。
function switchRoom(room) {
  if (room === activeRoom) return;
  activeRoom = room;

  const u = new URL(location.href);
  u.searchParams.set("room", room);
  history.replaceState(null, "", u);

  messagesEl.textContent = "";
  renderRooms();
  subscribe();
}
