**English** | [繁體中文](./README.zh.md)

# agent-notifier — MsgMesh event-watcher script

A Node script template that embodies MsgMesh's positioning: **an event layer for AI agents**. Subscribe to a topic and process events as they arrive — traditional pub/sub is for people or programs; here you feed the event stream into agent / backend logic.

- **Receive**: `@msgmesh/sdk`'s [`subscribe()`](https://www.npmjs.com/package/@msgmesh/sdk) — a long-polling loop over `GET {gateway}/v1/topics/{topic}/messages` that calls your handler on each message received and returns a stop function.
- Pure Node, no WebSocket needed; on transient errors the SDK backs off and retries automatically.

## poll/consume is a firehose — rooms don't apply here

`subscribe()` (and the underlying poll / consume) consumes the **whole topic** as a firehose: it uses the consumer-group offset to consume all partitions, with each message handled by exactly one consumer in the group (at-least-once, load-shared across the group). It does **not** do room filtering, because of a fundamental conflict:

- The consumer-group offset is the progress across the "whole topic"; per-room filtering would consume other rooms' messages and discard them while the offset advances anyway → lost messages.
- Forcing isolation with "one group per room" would mean every room reads the whole topic again (read amplification) — utterly uneconomical.

So the platform gates this kind of "whole-topic read" directly: **a poll/consume call with room-scoped credentials (a token whose `rooms` is non-empty) is rejected with 403**. This example needs a key with **no room restriction** (consumer/subscribe capability, empty `rooms` = all rooms) — it is meant to consume every event of the whole topic.

- **For per-room realtime processing** (handling only one room's events): use **realtime** — SSE `stream(topic, …, { room })` or WebSocket `streamWs(topic, …, { room })` (see [`chat-web`](../chat-web)). Realtime is a shared live-tail where per-room filtering is cheap.
- **For a backend worker doing whole-tenant consumption** (taking in every event from all of a tenant's rooms for DB / downstream work): use a key with **no room restriction** (as in this example), let one `subscribe` consume the whole topic, and split by reading `msg.key` (= the room) yourself in `handleEvent`.

## Run it

```bash
cp .env.example .env      # fill in the gateway URL and a consumer API key
npm install
npm start                 # = node --env-file=.env index.js
```

Once started, it prints a "subscribing to topic …" line, then prints each event as it arrives. Publish one to that topic (via `chat-web`, the SDK, or `curl`) and you'll see it pop up. `Ctrl-C` shuts down gracefully.

### Running on Node 18

The `--env-file` used by `npm start` needs Node ≥ 20.6. On Node 18, load the environment variables yourself instead:

```bash
export $(grep -v '^#' .env | xargs) && node index.js
```

## Configuration

| Variable | Purpose |
| --- | --- |
| `MSGMESH_GATEWAY_URL` | Address of the send/receive service |
| `MSGMESH_API_KEY` | API key (needs the consumer / subscribe capability, and **no room restriction** — poll consumes the whole topic, so a room-scoped token is rejected with 403) |
| `MSGMESH_TOPIC` | The topic to watch; defaults to `orders` |
| `MSGMESH_GROUP` | Consumer group; defaults to `agent-notifier` (multiple instances in the same group share the messages) |

## Adapt it to your use case

Edit `handleEvent(msg)` in `index.js`: `msg.value` is the raw string (the example tries to `JSON.parse` it). Replace the `console.log` with a DB write, a downstream API call, or a handoff to an LLM/agent decision. If your messages carry a room (the `key` at publish time), `msg.key` is the room name, which you can use for per-room routing (poll receives the all-rooms firehose; the splitting is up to you here).

## Files

- `index.js` — reads config, watches with `subscribe()`, processes events, shuts down gracefully.
- `.env.example` — config template (copy it to `.env`).
