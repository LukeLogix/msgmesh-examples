**English** | [繁體中文](./README.zh.md)

# agent-notifier-python — MsgMesh event-watcher script (Python)

The Python version of [`agent-notifier`](../agent-notifier): subscribe to a topic and process events as they arrive, so you can feed the event stream into agent / backend logic. The normal path matches the Node version (the same four settings, two startup lines in the same format, each prefixed with the script's own name, and the same command to publish a test event). Where the two differ is listed under "How it differs from the Node version" below.

- **Receive**: `subscribe()` from the [`msgmesh`](https://pypi.org/project/msgmesh/) SDK on PyPI — a long-polling loop over `GET {gateway}/v1/topics/{topic}/messages` that calls your handler on each message received and returns a function that stops the loop.
- The SDK's API is synchronous: the polling loop runs on a background thread, and no WebSocket is needed. On transient errors the SDK waits and retries on its own.

## poll/consume is a firehose — rooms don't apply here

`subscribe()` (and the underlying poll / consume) consumes the **whole topic** as a firehose: every message from every room, with each message handled by one consumer in the group (load-shared; delivery is **at-most-once** — the offset advances when a batch is fetched, so a message lost with a dropped response is not redelivered. For hard at-least-once processing, use webhooks or SSE/WS instead). It does **not** do room filtering, and **a poll/consume call with room-scoped credentials (a token whose `rooms` is non-empty) is rejected with 403**. This example needs a key with **no room restriction** (consumer/subscribe capability, empty `rooms` = all rooms).

Why poll cannot filter by room, and what to use when you only want one room's events, is explained in the section of the same name in the [`agent-notifier` README](../agent-notifier/README.md); it applies here unchanged. To split by room yourself, read `msg.room` in `handle_event`.

## Run it

You need Python ≥ 3.9 (check with `python3 --version`), plus an account, an API key and the `orders` topic: see "Common prerequisites" in the root README. The commands in this README are written for macOS and Linux; they have not been tried on Windows.

```bash
cp .env.example .env
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Open `.env` and fill in `MSGMESH_API_KEY`. For a try on your own machine, the starter key from the panel's one-click setup works (see "Common prerequisites" in the root README). `.env.example` already sets `MSGMESH_GATEWAY_URL` to `https://msgmesh-api.alderflux.com`; keep it. Then start the script:

```bash
.venv/bin/python main.py
```

`main.py` reads the `.env` next to it by itself: one `KEY=VALUE` per line. The value runs to the end of the line; only the whitespace around it, one pair of surrounding quotes and a leading `export` are removed. So do not put a comment at the end of a line: it would become part of the value. A variable that is already set in your shell wins over the file.

Once started, it prints these two lines, then prints each event as it arrives:

```
agent-notifier-python: subscribing to topic "orders" (group=agent-notifier-python)... press Ctrl-C to quit
agent-notifier-python: if this group has not read this topic before, it starts from the oldest message still within the topic's retention, so messages already in the topic arrive first
```

To see an event arrive, open a second terminal in this folder: the first line below exports every variable in `.env` into that shell (all four, not only `MSGMESH_API_KEY`), and the second publishes an event to `orders`. If you later start `main.py` in that same terminal, the exported values win over any change you have made to `.env` since.

```bash
export $(grep -v '^#' .env | xargs)
curl -X POST https://msgmesh-api.alderflux.com/v1/topics/orders/messages -H "Authorization: Bearer $MSGMESH_API_KEY" -H "Content-Type: application/json" -d '{"item":"test-order"}'
```

The response is `{"partition":…,"offset":…}`, and the event shows up in the first terminal as a line like this one (the time, partition and offset will be your own):

```
[2026-10-06T03:11:26.189Z] orders#0/0 {"item": "test-order"}
```

`Ctrl-C` stops the script; its exit code is 0.

**If no event shows up.** By default, when the topic does not exist (or its name is misspelled in `MSGMESH_TOPIC`), the receiving side reports no error: the script prints its two startup lines and then simply never shows an event, the same as for a topic that has no events yet. The `curl` above tells the two apart: when the topic has not been created, it is answered with an error (HTTP 404, topic not found) instead of `{"partition":…,"offset":…}`.

The second startup line matters whenever the group is new to the topic (how long the retention is depends on your plan). If you point `MSGMESH_TOPIC` at a topic that already has messages (for example `chat.lobby` after you have used `chat-web`), or switch to a different `MSGMESH_GROUP`, the script first receives the messages that are already there, and each delivery is counted in operations again, as usual (one operation per 16 KiB of the message: once when it is published and once more for every delivery). Restarting with the same group continues from where that group left off; a group that has been idle for a long time starts again from the oldest message still within the retention. The default group here is not the Node version's, so if you ran `agent-notifier` first and published test events, the first start of this script receives those events as well.

### If it stops right after starting

In the cases in the table below, the script prints the reason and exits with code 1:

| The message contains | What it means | What to do |
| --- | --- | --- |
| `Missing MSGMESH_API_KEY` | There is no `.env` next to `main.py`, or the key in it is empty or still `replace-me` | Fill in `MSGMESH_API_KEY` in `.env` |
| `MSGMESH_API_KEY contains a character that is not plain ASCII` | Something other than the key came along when it was copied | Copy the key again |
| `MSGMESH_API_KEY contains whitespace or a control character` | A space, a tab or a line break came along with the key | Copy the key again |
| `MSGMESH_GATEWAY_URL must start with https:// or http://` | The address is missing its scheme | Use `https://msgmesh-api.alderflux.com` |
| `.env is not UTF-8 text` | The file was saved in another encoding (UTF-16, for example) | Save `.env` as UTF-8 |
| `.env could not be read` | The file is there, but your user is not allowed to read it | Fix the permissions of `.env` |
| `as invalid (HTTP 400)` | The platform does not accept the request. Usually the topic name is not an allowed one, for example because a comment was put after the value in `.env` | Check `MSGMESH_TOPIC` |
| `the API key was rejected (HTTP 401)` | The key is wrong, or it has been deleted | Check `MSGMESH_API_KEY`; issue a new key if needed |
| `refused to let this key read topic` … `(HTTP 403)` | Usually the key lacks the consumer or subscribe capability on this topic (a key that can only publish cannot receive), or it is restricted to rooms | Use a key that can receive: see item 2 of "Common prerequisites" in the root README |
| `was not found (HTTP 404)` | You only get this when the account has turned on 「要求 topic 先建立(strict topics)」 ("require topics to be created first") on the panel's Keys page and the topic does not exist yet, or when `MSGMESH_GATEWAY_URL` points at something other than MsgMesh. With that setting off, as it is by default, a missing topic gives no error: see "If no event shows up" above | Create the topic in the panel, or point `MSGMESH_TOPIC` at one that exists; check the address shown in the message |

For the four with an HTTP status, the server's own reason is on the line after the message. If the key in use came from an environment variable and differs from the one in `.env`, one more line says so. That happens, for example, when you start `main.py` in the terminal where you ran the `export` line above and have changed `.env` since. If an error text contains the key itself, the key is printed as `***`.

Other errors (network trouble, a 5xx response, rate limiting) do not end the script: the SDK keeps retrying. The script prints a line starting with `agent-notifier-python: subscribe error`, with the exception class and the gateway address. While the same kind of error keeps happening, that line is printed at most once every 30 seconds: the first line carries no count, and from the second one on it says how many errors of that kind there have been so far.

If whatever reads the script's output goes away (for example when the output is piped into `head -1`), the script notices the next time it has something to print: it stops without printing anything more and exits with code 1. Until then (while no event arrives) it keeps waiting as usual.

### How it differs from the Node version

- **Default group.** `agent-notifier-python`, not `agent-notifier`. Instances in the same group share the messages; with one name for both, running the two examples at once would show each event in only one of them.
- **HTTP 400 / 401 / 403 / 404.** On a 401 both versions end: the Node version prints one line and exits with code 0; this one prints the reason and exits with code 1 (the Python SDK stops polling for good on a 401, so a script that stayed alive would sit there doing nothing). With a key that cannot read the topic (403), the Node version keeps retrying and prints an error line on each attempt, waiting longer after each consecutive failure (up to a second at first, doubling up to 30 seconds; `@msgmesh/sdk` 0.7.0); this one prints the reason and exits. A 400, and a 404 (which only a strict-topics account gets for a missing topic), go the same way as the 403 in both versions. A 403 is not always permanent, so in a long-running worker you may prefer to keep retrying: change the 403 branch of `report` in `main.py` so that it prints instead of calling `give_up`.
- **A key that is still `replace-me` counts as missing**, and the key and the address are checked before any request is sent. The Node version only checks that the key is not empty.
- **`MSGMESH_GATEWAY_URL` has a default.** When the variable is not set at all, `main.py` uses `https://msgmesh-api.alderflux.com`.
- **`.env` is read by `main.py`**, not by the runtime (`node --env-file`).
- **Events are printed as JSON text** (`{"item": "test-order"}`); the Node version prints the parsed object (`{ item: 'test-order' }`).

## Configuration

| Variable | Purpose |
| --- | --- |
| `MSGMESH_GATEWAY_URL` | Address of the send/receive service: `https://msgmesh-api.alderflux.com` (already set in `.env.example`; also what `main.py` uses when the variable is not set) |
| `MSGMESH_API_KEY` | API key (needs the consumer / subscribe capability, and **no room restriction** — poll consumes the whole topic, so a room-scoped token is rejected with 403) |
| `MSGMESH_TOPIC` | The topic to watch; defaults to `orders`, which the panel's one-click setup creates by default. Only on an account that already existed, or if you unticked that option, create it yourself first (see "Common prerequisites" in the root README) |
| `MSGMESH_GROUP` | Consumer group; defaults to `agent-notifier-python` (multiple instances in the same group share the messages). A new group starts from the oldest message within the topic's retention |

## Adapt it to your use case

Edit `handle_event(msg)` in `main.py`: `msg.value` is the raw string (the example tries `json.loads` on it), and `msg.partition` and `msg.offset` say where the message sits in the topic. Replace the `say(...)` call with a DB write, a downstream API call, or a handoff to an LLM/agent decision. If your messages carry a room (the `room` at publish time), `msg.room` is the room name (`None` when there was none), which you can use for per-room routing (poll receives the all-rooms firehose; the splitting is up to you here).

The handler runs on the SDK's background thread, one message at a time, so a slow handler delays the next poll. The SDK is synchronous; inside an async framework, run it in an executor yourself.

If `handle_event` raises, the script prints the traceback and goes on with the next message. That comes from the `try` in `on_message`: without it, the SDK (0.7.0) hands the exception to `on_error` and skips the rest of the batch it had already fetched, and those messages are not delivered again. Either way, a message whose handling failed is not retried.

## Files

- `main.py` — reads `.env`, checks the settings, watches with `subscribe()`, processes events, stops on `Ctrl-C` or SIGTERM.
- `requirements.txt` — the SDK pinned to an exact version (there is no lockfile, so that line decides which SDK you get).
- `.env.example` — config template (copy it to `.env`).
