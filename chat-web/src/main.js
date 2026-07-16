// chat-web —— 最小網頁聊天室:用 @msgmesh/sdk 的 stream()(SSE)即時收訊、publish() 發訊。
// 設定從 Vite 注入的環境變數讀取(見 .env.example)。
import { MsgMesh } from "@msgmesh/sdk";

const env = import.meta.env;
const cfg = {
  gatewayUrl: env.VITE_MSGMESH_GATEWAY_URL,
  realtimeUrl: env.VITE_MSGMESH_REALTIME_URL,
  apiKey: env.VITE_MSGMESH_API_KEY,
  topic: env.VITE_MSGMESH_TOPIC || "chat.lobby",
};

const $ = (id) => document.getElementById(id);
const messagesEl = $("messages");
const form = $("composer");
const textInput = $("text");
const nameInput = $("name");
const statusEl = $("status");
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

// 設定不齊全時直接在畫面提示,不硬連線(避免一堆 console 錯誤看不懂)。
if (!cfg.gatewayUrl || !cfg.realtimeUrl || !cfg.apiKey || cfg.apiKey === "replace-me") {
  setStatus("尚未設定:請複製 .env.example 成 .env,填入 gateway/realtime URL 與 API key,再重啟 dev server。", "error");
  sendBtn.disabled = true;
} else {
  start();
}

function start() {
  const mq = new MsgMesh({
    apiKey: cfg.apiKey,
    gatewayUrl: cfg.gatewayUrl,
    realtimeUrl: cfg.realtimeUrl,
  });

  // 收:SSE 即時串流。回呼收到的是「訊息 value 字串」——我們發的是 JSON,故先 parse。
  // stream() 回傳停止函式;此範例整頁存活,不需主動停止。
  mq.stream(
    cfg.topic,
    (data) => {
      let payload;
      try {
        payload = JSON.parse(data);
      } catch {
        payload = { text: data };
      }
      addMessage(payload, payload.user === nameInput.value.trim());
    },
    (err) => {
      console.error("stream 錯誤:", err);
      setStatus("連線中斷,SDK 會自動重連(詳見 console)。", "error");
    },
  );

  // EventSource 沒有暴露 onopen 回呼,連上但還沒訊息時無從得知;先樂觀標示就緒,
  // 真正斷線時上面的 onError 會覆蓋成錯誤狀態。
  setStatus(`已連線 · topic: ${cfg.topic}(等待訊息)`, "ok");

  // 發:publish JSON 物件。訊息會經 SSE 回流,由上面的 stream 回呼統一渲染(含自己這筆)。
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = textInput.value.trim();
    if (!text) return;
    const user = nameInput.value.trim() || "anon";
    textInput.value = "";
    try {
      await mq.publish(cfg.topic, { user, text, ts: Date.now() });
    } catch (err) {
      console.error("publish 失敗:", err);
      setStatus("送出失敗:" + (err?.message || err), "error");
      textInput.value = text; // 還原內容,方便重送
    }
  });
}
