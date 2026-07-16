// agent-notifier —— 訂閱一個 MsgMesh topic,收到事件就處理。
//
// 這體現 MsgMesh 的定位:「給 AI agent 的事件層」。這裡示範把事件印出來;
// 把 handleEvent 換成你要的動作即可:寫入 DB、呼叫下游 webhook、丟給 LLM/agent 做決策…
//
// 用 @msgmesh/sdk 的 subscribe():內部是長輪詢迴圈,回傳一個停止函式。Node 端不需 WebSocket。
import { MsgMesh } from "@msgmesh/sdk";

const {
  MSGMESH_API_KEY,
  MSGMESH_GATEWAY_URL,
  MSGMESH_TOPIC = "orders",
  MSGMESH_GROUP = "agent-notifier",
} = process.env;

if (!MSGMESH_API_KEY) {
  console.error("缺少 MSGMESH_API_KEY:請複製 .env.example 成 .env 並填入(收訊需 consumer 能力的 key)。");
  process.exit(1);
}

const mq = new MsgMesh({
  apiKey: MSGMESH_API_KEY,
  gatewayUrl: MSGMESH_GATEWAY_URL, // 收發都走 gateway;subscribe 只用到它
});

// 換成你自己的處理邏輯。msg.value 是字串;我們的發送端送 JSON,故先試著 parse。
async function handleEvent(msg) {
  let payload = msg.value;
  try {
    payload = JSON.parse(msg.value);
  } catch {
    // 非 JSON 就當純字串處理
  }
  console.log(
    `[${new Date().toISOString()}] ${MSGMESH_TOPIC}#${msg.partition}/${msg.offset}`,
    payload,
  );
}

console.log(`agent-notifier:訂閱 topic "${MSGMESH_TOPIC}"(group=${MSGMESH_GROUP})… 按 Ctrl-C 結束`);

// subscribe(topic, opts, handler) → 停止函式。
// onError:每次輪詢出錯時回報(暫時性錯誤 SDK 會自動退避重試;金鑰失效等終態才會停)。
const stop = mq.subscribe(
  MSGMESH_TOPIC,
  {
    group: MSGMESH_GROUP,
    onError: (err) => console.error("訂閱錯誤(SDK 會自動重試):", err?.message || err),
  },
  handleEvent,
);

// 優雅結束:停止輪詢迴圈後退出。
for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => {
    console.log(`\n收到 ${sig},停止訂閱。`);
    stop();
    process.exit(0);
  });
}
