// agent-notifier — subscribes to one MsgMesh topic and handles every event it receives.
//
// This embodies MsgMesh's positioning: "the event layer for AI agents". Here the events are
// printed; swap handleEvent for whatever you need: write to a DB, call a downstream webhook,
// hand it to an LLM/agent for a decision...
//
// Uses @msgmesh/sdk's subscribe(): a long-polling loop inside, returning a stop function.
// No WebSocket needed on the Node side.
import { MsgMesh } from "@msgmesh/sdk";

const {
  MSGMESH_API_KEY,
  MSGMESH_GATEWAY_URL,
  MSGMESH_TOPIC = "orders",
  MSGMESH_GROUP = "agent-notifier",
} = process.env;

if (!MSGMESH_API_KEY) {
  console.error("Missing MSGMESH_API_KEY: copy .env.example to .env and fill it in (receiving needs a key with the consumer capability).");
  process.exit(1);
}

const mq = new MsgMesh({
  apiKey: MSGMESH_API_KEY,
  gatewayUrl: MSGMESH_GATEWAY_URL, // both send and receive go through the gateway; subscribe only uses this
});

// Replace with your own handling logic. msg.value is a string; our sender publishes JSON, so try
// parsing it first. This is a firehose: it receives every message on the whole topic (all rooms).
// msg.room = the room passed at publish time; for per-room dispatch, read msg.room here and branch
// yourself (the platform's room filtering only exists on realtime SSE/WS, not on poll).
// `?? msg.key` keeps compatibility with older platforms: room is the new name — older responses
// call this field key — accepting both works on every version.
async function handleEvent(msg) {
  let payload = msg.value;
  try {
    payload = JSON.parse(msg.value);
  } catch {
    // not JSON — treat it as a plain string
  }
  const roomName = msg.room ?? msg.key;
  const room = roomName ? ` room=${roomName}` : "";
  console.log(
    `[${new Date().toISOString()}] ${MSGMESH_TOPIC}#${msg.partition}/${msg.offset}${room}`,
    payload,
  );
}

console.log(`agent-notifier: subscribing to topic "${MSGMESH_TOPIC}" (group=${MSGMESH_GROUP})... press Ctrl-C to quit`);

// subscribe(topic, opts, handler) → stop function.
// onError: reports every polling error (the SDK backs off and retries transient errors on its own;
// only terminal states like a revoked key stop the loop).
const stop = mq.subscribe(
  MSGMESH_TOPIC,
  {
    group: MSGMESH_GROUP,
    onError: (err) => console.error("subscribe error (the SDK retries automatically):", err?.message || err),
  },
  handleEvent,
);

// Graceful shutdown: stop the polling loop, then exit.
for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => {
    console.log(`\nReceived ${sig}, stopping the subscription.`);
    stop();
    process.exit(0);
  });
}
