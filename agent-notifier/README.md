**English** | [繁體中文](./README.zh.md)

# agent-notifier — MsgMesh event-watcher script

A Node script template that embodies MsgMesh's positioning: **an event layer for AI agents**. Subscribe to a topic and process events as they arrive — traditional pub/sub is for people or programs; here you feed the event stream into agent / backend logic.

- **Receive**: `@msgmesh/sdk`'s [`subscribe()`](https://www.npmjs.com/package/@msgmesh/sdk) — a long-polling loop over `GET {gateway}/v1/topics/{topic}/messages` that calls your handler on each message received and returns a stop function.
- Pure Node, no WebSocket needed; on transient errors the SDK backs off and retries automatically.

## poll/consume is a firehose — rooms don't apply here

`subscribe()` (and the underlying poll / consume) consumes the **whole topic** as a firehose: it uses the consumer-group offset to consume all partitions, with each message handled by exactly one consumer in the group (load-shared; delivery is **at-most-once** — the offset advances when a batch is fetched, so a message lost with a dropped response is not redelivered. For hard at-least-once processing, use webhooks or SSE/WS instead). It does **not** do room filtering, because of a fundamental conflict:

- The consumer-group offset is the progress across the "whole topic"; per-room filtering would consume other rooms' messages and discard them while the offset advances anyway → lost messages.
- Forcing isolation with "one group per room" would mean every room reads the whole topic again (read amplification) — utterly uneconomical.

So the platform gates this kind of "whole-topic read" directly: **a poll/consume call with room-scoped credentials (a token whose `rooms` is non-empty) is rejected with 403**. This example needs a key with **no room restriction** (consumer/subscribe capability, empty `rooms` = all rooms) — it is meant to consume the whole topic's event stream.

- **For per-room realtime processing** (handling only one room's events): use **realtime** — SSE `stream(topic, …, { room })` or WebSocket `streamWs(topic, …, { room })` (see [`chat-web`](../chat-web)). Realtime is a shared live-tail where per-room filtering is cheap.
- **For a backend worker doing whole-tenant consumption** (taking in the stream from all of a tenant's rooms for DB / downstream work): use a key with **no room restriction** (as in this example), let one `subscribe` consume the whole topic, and split by reading `msg.room` (= the room) yourself in `handleEvent`.

## Run it

```bash
cp .env.example .env
npm install
```

Open `.env` and fill in `MSGMESH_API_KEY`. For a try on your own machine, the starter key from the panel's one-click setup works (see "Common prerequisites" in the root README). `.env.example` already sets `MSGMESH_GATEWAY_URL` to `https://msgmesh-api.alderflux.com`; keep it. Then start the script (`npm start` runs `node --env-file=.env index.js`):

```bash
npm start
```

Once started, it prints these two lines, then prints each event as it arrives:

```
agent-notifier: subscribing to topic "orders" (group=agent-notifier)... press Ctrl-C to quit
agent-notifier: if this group has not read this topic before, it starts from the oldest message still within the topic's retention, so messages already in the topic arrive first
```

To see an event arrive, open a second terminal in this folder: the first line below loads `MSGMESH_API_KEY` from `.env` into that shell, and the second publishes an event to `orders`.

```bash
export $(grep -v '^#' .env | xargs)
curl -X POST https://msgmesh-api.alderflux.com/v1/topics/orders/messages -H "Authorization: Bearer $MSGMESH_API_KEY" -H "Content-Type: application/json" -d '{"item":"test-order"}'
```

The response is `{"partition":…,"offset":…}`, and the event pops up in the first terminal. `Ctrl-C` shuts down gracefully.

By default, when the topic does not exist (or its name is misspelled in `MSGMESH_TOPIC`), the receiving side reports no error and the script simply never shows an event; the signal is the `curl` above, which is answered with an error (HTTP 404, topic not found) when the topic has not been created.

The second startup line matters whenever the group is new to the topic (how long the retention is depends on your plan). If you point `MSGMESH_TOPIC` at a topic that already has messages (for example `chat.lobby` after you have used `chat-web`), or switch to a different `MSGMESH_GROUP`, the script first receives the messages that are already there, and each delivery is counted in operations again, as usual (one operation per 16 KiB of the message: once when it is published and once more for every delivery). Restarting with the same group continues from where that group left off; a group that has been idle for a long time starts again from the oldest message still within the retention.

### Running on Node 18

The `--env-file` used by `npm start` needs Node ≥ 20.6. On Node 18, load the environment variables yourself instead:

```bash
export $(grep -v '^#' .env | xargs) && node index.js
```

## Configuration

| Variable | Purpose |
| --- | --- |
| `MSGMESH_GATEWAY_URL` | Address of the send/receive service: `https://msgmesh-api.alderflux.com` (already set in `.env.example`) |
| `MSGMESH_API_KEY` | API key (needs the consumer / subscribe capability, and **no room restriction** — poll consumes the whole topic, so a room-scoped token is rejected with 403) |
| `MSGMESH_TOPIC` | The topic to watch; defaults to `orders`, which the panel's one-click setup creates by default. Only on an account that already existed, or if you unticked that option, create it yourself first (see "Common prerequisites" in the root README) |
| `MSGMESH_GROUP` | Consumer group; defaults to `agent-notifier` (multiple instances in the same group share the messages). A new group starts from the oldest message within the topic's retention |

## Adapt it to your use case

Edit `handleEvent(msg)` in `index.js`: `msg.value` is the raw string (the example tries to `JSON.parse` it). Replace the `console.log` with a DB write, a downstream API call, or a handoff to an LLM/agent decision. If your messages carry a room (the `room` at publish time), `msg.room` is the room name, which you can use for per-room routing (poll receives the all-rooms firehose; the splitting is up to you here).

## Files

- `index.js` — reads config, watches with `subscribe()`, processes events, shuts down gracefully.
- `.env.example` — config template (copy it to `.env`).
