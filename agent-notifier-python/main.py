"""agent-notifier-python — subscribes to one MsgMesh topic and handles every event it receives.

The Python counterpart of ../agent-notifier: the same settings and the same normal path (the
README lists where the two differ). Here the events are printed; swap handle_event for whatever
you need: write to a DB, call a downstream API, hand it to an LLM/agent for a decision...

Uses the msgmesh SDK's subscribe(): a long-polling loop on a background thread; it returns a
function that stops the loop. The SDK is synchronous, so there is no asyncio here.
"""
import json
import os
import signal
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from msgmesh import AuthError, MsgMesh, NotFoundError, ValidationError

NAME = "agent-notifier-python"
SERVICE_URL = "https://msgmesh-api.alderflux.com"
PLACEHOLDER_KEY = "replace-me"
# While the SDK keeps retrying, the same kind of error is printed at most once per this many seconds.
ERROR_REPEAT_SECONDS = 30
SHORTEST_REDACTED_KEY = 8  # see redact()


def read_env_file(path):
    """Returns the KEY=VALUE lines of .env as a dict (Python has no --env-file).

    Deliberately minimal: blank lines and lines starting with # are skipped, a leading "export "
    is dropped, and one pair of surrounding quotes is removed. There are no end-of-line comments:
    the value runs to the end of the line (only the whitespace around it and that one pair of quotes
    are removed). If you need more than this, use the python-dotenv package.

    Raises UnicodeError when the file is not UTF-8 text, and OSError when it cannot be read.
    """
    values = {}
    if not path.is_file():
        return values
    # utf-8-sig: some editors put a byte-order mark at the start of the file.
    text = path.read_text(encoding="utf-8-sig")
    if "\x00" in text:
        # UTF-16 without a byte-order mark decodes as UTF-8 "successfully", with a NUL after every
        # character; a NUL can never be part of an environment variable either.
        raise UnicodeError("NUL character in .env")
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name:
            continue  # a line like "=foo" names no variable
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    return values


# .env sits next to this file, so the script works from any working directory.
try:
    FILE_VALUES = read_env_file(Path(__file__).resolve().parent / ".env")
except UnicodeError:
    sys.exit(f"{NAME}: .env is not UTF-8 text. Save it as UTF-8 and start again.")
except OSError as _err:
    sys.exit(
        f"{NAME}: .env could not be read ({_err.strerror or _err}). Check that your user is allowed "
        "to read the file, then start again."
    )

# A variable that is already set in the environment wins over the file, like Node's --env-file.
for _name, _value in FILE_VALUES.items():
    os.environ.setdefault(_name, _value)

API_KEY = os.environ.get("MSGMESH_API_KEY", "")
GATEWAY_URL = os.environ.get("MSGMESH_GATEWAY_URL") or SERVICE_URL
TOPIC = os.environ.get("MSGMESH_TOPIC") or "orders"
GROUP = os.environ.get("MSGMESH_GROUP") or NAME

# Event payloads can contain characters the terminal's encoding lacks; print them escaped
# instead of raising.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="backslashreplace")


def say(text):
    print(text, flush=True)


def redact(text):
    """Replaces the API key with *** wherever it appears in text.

    Error text written by libraries can quote the request, Authorization header included. Keys
    shorter than SHORTEST_REDACTED_KEY characters are left alone: no real key is that short, and
    replacing, say, every "a" would only make the message unreadable.
    """
    forms = {API_KEY, API_KEY.strip(), repr(API_KEY)[1:-1]}
    for form in sorted(forms, key=len, reverse=True):
        if len(form) >= SHORTEST_REDACTED_KEY:
            text = text.replace(form, "***")
    return text


def complain(text):
    print(redact(text), file=sys.stderr, flush=True)


def config_problem():
    """Returns why the settings cannot work, or None. Checked before any request is sent."""
    if not API_KEY or API_KEY == PLACEHOLDER_KEY:
        return (
            "Missing MSGMESH_API_KEY: copy .env.example to .env and fill it in "
            "(receiving needs a key with the consumer or subscribe capability)."
        )
    if not API_KEY.isascii():
        return (
            f"{NAME}: MSGMESH_API_KEY contains a character that is not plain ASCII (often an "
            "ellipsis or an invisible character picked up while copying). Copy the key again."
        )
    if not API_KEY.isprintable() or any(ch.isspace() for ch in API_KEY):
        return (
            f"{NAME}: MSGMESH_API_KEY contains whitespace or a control character (a space, a tab or "
            "a line break, often picked up while copying). Copy the key again."
        )
    if not GATEWAY_URL.startswith(("http://", "https://")):
        return (
            f"{NAME}: MSGMESH_GATEWAY_URL must start with https:// or http:// "
            f"(it is {GATEWAY_URL!r}). MsgMesh's service address is {SERVICE_URL}."
        )
    return None


def key_source_note():
    """One more line for a rejected key, when the key in use is not the one written in .env."""
    in_file = FILE_VALUES.get("MSGMESH_API_KEY")
    if in_file is None or in_file == API_KEY:
        return ""
    if not in_file or in_file == PLACEHOLDER_KEY:
        # Nothing usable in .env, so "use the key in .env" would be the wrong advice.
        return (
            "\n  Note: the key in use comes from the MSGMESH_API_KEY environment variable; the one "
            "in .env is not filled in."
        )
    return (
        "\n  Note: the key in use comes from the MSGMESH_API_KEY environment variable, not from "
        ".env (a variable that is already set wins over the file). Unset it, or open a new "
        "terminal, to use the key in .env."
    )


def handle_event(msg):
    """Replace with your own handling logic.

    msg.value is a string; our sender publishes JSON, so try parsing it first. This is a
    firehose: it receives every message on the whole topic (all rooms). msg.room is the room
    passed at publish time (None when there was none); for per-room dispatch, read msg.room here
    and branch yourself (the platform's room filtering only exists on realtime SSE/WS, not on
    poll).
    """
    try:
        payload = json.dumps(json.loads(msg.value), ensure_ascii=False)
    except ValueError:
        payload = msg.value  # not JSON — treat it as a plain string
    room = f" room={msg.room}" if msg.room else ""
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    say(f"[{now}] {TOPIC}#{msg.partition}/{msg.offset}{room} {payload}")


def main():
    problem = config_problem()
    if problem:
        complain(problem)
        return 1

    # Receiving goes through the gateway; subscribe() only uses gateway_url.
    mq = MsgMesh(api_key=API_KEY, gateway_url=GATEWAY_URL)

    done = threading.Event()  # set when the script should end
    state = {"exit_code": 0, "why": None}
    retried = {}  # kind of error -> [how many so far, when it was last printed]
    # Printing happens on two threads: the SDK's background thread (events, errors) and the main
    # thread (the last line before exiting). Both print only while holding this lock, and the
    # background thread first checks that the script is not ending. Without that, the main thread
    # could leave while the other one is in the middle of a print, and the interpreter can abort
    # at shutdown when a daemon thread still holds the lock of sys.stdout.
    printing = threading.Lock()

    def finish(why, exit_code):
        if not done.is_set():
            state["why"], state["exit_code"] = why, exit_code
            done.set()

    def output_closed():
        # Whatever was reading our output went away (for example `python main.py | head -1`).
        # Nothing more can be printed, so stop quietly instead of treating it as a handler error.
        finish("output closed", 1)
        try:
            # Point stdout at /dev/null so the flush Python does at exit has somewhere to go.
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError):
            pass

    def give_up(text):
        complain(text + key_source_note())
        finish("gave up", 1)

    def report(err):
        status = getattr(err, "status", None)
        if isinstance(err, AuthError) and status == 401:
            # The SDK stops polling for good on a 401, so staying alive would only look like a hang.
            give_up(
                f"{NAME}: the API key was rejected (HTTP 401). The key is wrong, or it has been "
                f"deleted; check MSGMESH_API_KEY. The server's reason is on the next line.\n  {err}"
            )
        elif isinstance(err, AuthError):
            # 403. The SDK would keep retrying, but with a key that cannot read this topic that
            # never succeeds, so stop and say why. (A 403 can also be a suspension the account
            # owner can lift; in a long-running worker you may prefer to let the SDK keep retrying.)
            give_up(
                f'{NAME}: the platform refused to let this key read topic "{TOPIC}" (HTTP 403). '
                "Usually the key lacks the consumer or subscribe capability on this topic (a key "
                "that can only publish cannot receive), or it is restricted to rooms. The "
                f"server's reason is on the next line.\n  {err}"
            )
        elif isinstance(err, NotFoundError):
            # Only an account that has turned on "strict topics" in the panel gets here for a topic
            # that does not exist. By default the platform answers a subscription to a missing
            # topic with 200 and an empty list, so this script just keeps waiting, the same as for
            # a topic with no events yet. (Publishing to a missing topic is a 404 either way.)
            give_up(
                f'{NAME}: {GATEWAY_URL} answered that topic "{TOPIC}" was not found (HTTP 404). '
                "Either this account requires topics to be created first (the strict topics "
                "setting in the panel) and this topic does not exist yet: create it in the panel, "
                "or point MSGMESH_TOPIC at one that exists. Or MSGMESH_GATEWAY_URL is not the "
                f"MsgMesh service address ({SERVICE_URL}) and something else answered. The "
                f"server's reason is on the next line.\n  {err}"
            )
        elif isinstance(err, ValidationError):
            # 400 (or 422): the request itself is not acceptable, so the same request can never
            # succeed. The usual cause is a topic name the platform does not allow.
            give_up(
                f'{NAME}: the platform rejected the request for topic "{TOPIC}" as invalid '
                f"(HTTP {status}). Usually the topic name is not an allowed one: check "
                "MSGMESH_TOPIC. A value in .env runs to the end of its line, so do not put a "
                f"comment after it. The server's reason is on the next line.\n  {err}"
            )
        else:
            # Anything else (network trouble, 5xx, rate limiting): the SDK waits and retries on its
            # own. Print the same kind of error at most once per ERROR_REPEAT_SECONDS, with a count.
            kind = (type(err).__name__, status)
            seen = retried.setdefault(kind, [0, None])
            seen[0] += 1
            now = time.monotonic()
            if seen[1] is None or now - seen[1] >= ERROR_REPEAT_SECONDS:
                seen[1] = now
                label = type(err).__name__ + (f", HTTP {status}" if status else "")
                count = f", {seen[0]} errors of this kind so far" if seen[0] > 1 else ""
                complain(
                    f"{NAME}: subscribe error ({label}{count}) from {GATEWAY_URL}; the SDK keeps "
                    f"retrying, and the same kind of error is printed at most once every "
                    f"{ERROR_REPEAT_SECONDS} seconds: {err}"
                )

    def on_error(err):
        # Runs on the SDK's background thread, once per failed poll.
        with printing:
            if done.is_set():
                return
            try:
                report(err)
            except BrokenPipeError:
                output_closed()

    def on_message(msg):
        # Runs on the SDK's background thread, once per message.
        with printing:
            if done.is_set():
                return
            try:
                handle_event(msg)
            except BrokenPipeError:
                output_closed()
            except Exception:
                # Without this, the SDK would hand the exception to on_error and skip the rest of
                # the batch it had already fetched; those messages are not delivered again.
                try:
                    complain(traceback.format_exc().rstrip("\n"))
                except BrokenPipeError:
                    output_closed()

    try:
        say(f'{NAME}: subscribing to topic "{TOPIC}" (group={GROUP})... press Ctrl-C to quit')
        say(
            f"{NAME}: if this group has not read this topic before, it starts from the oldest "
            "message still within the topic's retention, so messages already in the topic arrive first"
        )
    except BrokenPipeError:
        output_closed()
        return state["exit_code"]

    # SIGTERM (docker stop, a process manager) ends the script the same way Ctrl-C does.
    signal.signal(signal.SIGTERM, lambda signum, frame: finish("SIGTERM", 0))

    # subscribe(topic, handler, group=..., on_error=...) returns immediately; the polling runs on a
    # daemon thread, so the main thread has to stay alive until it is time to stop.
    stop = mq.subscribe(TOPIC, on_message, group=GROUP, on_error=on_error)

    try:
        while not done.wait(0.5):
            pass
    except KeyboardInterrupt:
        finish("Ctrl-C", 0)
    stop()
    try:
        # Taking the lock waits for a message that is being handled right now; after that the
        # background thread prints nothing more (it sees that the script is ending).
        with printing:
            if state["why"] in ("SIGTERM", "Ctrl-C"):
                say(f"\nReceived {state['why']}, stopping the subscription.")
    except BrokenPipeError:
        output_closed()
    except KeyboardInterrupt:
        pass  # a second Ctrl-C while a slow handler is still running: leave now
    return state["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
