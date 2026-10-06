# py-run-smoke —— 把 Python 範例真的跑起來,對一個本機的假 gateway 收訊息。
#
# 為什麼需要它:py_compile 只證明語法過得去;「裝得起來」也不代表「跑起來會收到東西」。
# JS 範例在 CI 裡沒辦法連線,只能做靜態的 api-smoke;Python 範例只打一支 HTTP 端點
# (GET /v1/topics/{topic}/messages),假得起來,所以這裡直接跑。不需要任何憑證,不連外。
#
# 守的東西(每個情境各自寫在下面):
#   · requirements.txt 第一行是確切版本的 msgmesh,而且裝到的就是那一版;httpx 有上限
#   · 照 README 的做法(.env.example 複製成 .env、只改 key)啟動得了,而且真的收到並印出事件
#   · 啟動時印的兩行、預設 topic / group / 服務位址、Authorization 標頭、環境變數優先於 .env
#   · key 沒填 / 含非 ASCII 字元、位址沒有 http(s)://、.env 不是 UTF-8 → 印原因後結束,不打任何請求
#   · 401 / 403 / 404 → 印出原因後以 1 結束(SDK 在 401 會停止輪詢,範例不結束就是無聲卡死)
#   · 其他錯誤 → 不結束、SDK 重試後照樣收得到;同一種錯誤不洗版,但隔一段時間會再印一次
#   · 處理函式丟例外 → 同一批後面的訊息照樣處理
#   · Ctrl-C(SIGINT)與 SIGTERM → 以 0 結束
#
# 用法:在範例目錄底下執行 `python ../scripts/py-run-smoke.py`(用已安裝 requirements.txt 的直譯器)。
# 只用標準函式庫。範例目錄會被複製到暫存目錄再跑,不會動到你自己的 .env。
# 只支援 macOS / Linux(用到 SIGINT / SIGTERM);CI 也只在 Linux 上跑它。

import ast
import importlib.metadata
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

# 這支腳本自己的輸出有中文與符號;終端不是 UTF-8 時也不該在印訊息時炸掉。
for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")

EXAMPLE = Path.cwd()
ENTRY = "main.py"
SMOKE_KEY = "smoke-key-not-a-real-credential"
OTHER_KEY = "another-smoke-key-not-a-real-credential"
PLACEHOLDER = "replace-me"
SERVICE_URL = "https://msgmesh-api.alderflux.com"
REPEAT_LINE = "ERROR_REPEAT_SECONDS = 30"  # main.py 裡的這一行;節流情境會在副本裡把它改短
WAIT = 20.0  # 每個等待的上限(秒);正常情況遠低於此

failures = []


def fail(scenario, text, run=None):
    failures.append(scenario)
    print(f"✗ [{scenario}] {text}")
    if run is not None:
        print("  ── stdout ──")
        for line in run.out:
            print(f"  | {line}")
        print("  ── stderr ──")
        for line in run.err:
            print(f"  | {line}")
        print(f"  ── 假 gateway 收到 {len(run.gateway.requests)} 個請求 ──")
        for req in run.gateway.requests[:10]:
            print(f"  | {req['path']}?{req['query']}")


class FakeGateway:
    """只認 GET /v1/topics/{topic}/messages。script(n, req) 決定第 n 個請求(從 1 起算)回什麼。"""

    def __init__(self, script):
        self.requests = []
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server 的命名
                parts = urlsplit(self.path)
                req = {
                    "path": parts.path,
                    "query": parts.query,
                    "params": parse_qs(parts.query),
                    "auth": self.headers.get("Authorization", ""),
                }
                with outer._lock:
                    outer.requests.append(req)
                    n = len(outer.requests)
                status, body = script(n, req)
                if status == 200 and not body.get("messages"):
                    time.sleep(0.2)  # 真的 gateway 沒訊息時會掛著等;這裡短短等一下,免得空轉
                data = json.dumps(body).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # 範例已經結束、連線斷了:情境本來就會走到這裡,不是錯誤

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.host = f"127.0.0.1:{self._server.server_address[1]}"
        self.url = f"http://{self.host}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()


def env_from_example(key, gateway_url):
    """照 README:把 .env.example 複製成 .env,只換 key(與測試用的 gateway 位址)。

    換不到那一行就紅 —— 代表 .env.example 與程式讀的變數名對不上了。
    """
    lines = (EXAMPLE / ".env.example").read_text(encoding="utf-8").splitlines()
    seen = set()
    out = []
    for line in lines:
        if line.startswith("MSGMESH_API_KEY="):
            seen.add("key")
            line = f"MSGMESH_API_KEY={key}"
        elif line.startswith("MSGMESH_GATEWAY_URL="):
            seen.add("url")
            line = f"MSGMESH_GATEWAY_URL={gateway_url}"
        out.append(line)
    if seen != {"key", "url"}:
        raise SystemExit("✗ .env.example 少了 MSGMESH_API_KEY= 或 MSGMESH_GATEWAY_URL= 這一行")
    return "\n".join(out) + "\n"


class Run:
    """在暫存目錄裡啟動一份範例,收集它的輸出。

    dotenv(gateway) 回傳 .env 的內容(str 或 bytes);不給就是「.env.example 只換 key 與位址」。
    environ(gateway) 回傳要額外放進環境的變數;patch(text) 可以改副本裡的 main.py。
    """

    def __init__(self, scenario, script, key=SMOKE_KEY, dotenv=None, environ=None, patch=None):
        self.scenario = scenario
        self.gateway = FakeGateway(script)
        self.tmp = Path(tempfile.mkdtemp(prefix="py-run-smoke-"))
        self.copy = self.tmp / "example"
        shutil.copytree(
            EXAMPLE,
            self.copy,
            ignore=shutil.ignore_patterns(".env", ".venv", "venv", "__pycache__"),
        )
        content = dotenv(self.gateway) if dotenv else env_from_example(key, self.gateway.url)
        if isinstance(content, str):
            content = content.encode("utf-8")
        (self.copy / ".env").write_bytes(content)
        if patch:
            entry = self.copy / ENTRY
            entry.write_text(patch(entry.read_text(encoding="utf-8")), encoding="utf-8")
        # 環境裡的 MSGMESH_* 一律拿掉:設定只能來自剛寫好的 .env(與情境自己給的變數),否則測不到讀檔那段。
        # PYTHONUNBUFFERED 也拿掉:它會蓋掉「輸出有沒有即時送出」這件事。
        env = {k: v for k, v in os.environ.items() if not k.startswith("MSGMESH_") and k != "PYTHONUNBUFFERED"}
        env["NO_PROXY"] = "127.0.0.1,localhost"
        if environ:
            env.update(environ(self.gateway))
        # cwd 刻意不是範例目錄:.env 必須是從腳本所在位置找到的。
        self.proc = subprocess.Popen(
            [sys.executable, str(self.copy / ENTRY)],
            cwd=str(self.tmp),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.out, self.err, self.err_at = [], [], []
        threading.Thread(target=self._pump, args=(self.proc.stdout, self.out, None), daemon=True).start()
        threading.Thread(target=self._pump, args=(self.proc.stderr, self.err, self.err_at), daemon=True).start()

    @staticmethod
    def _pump(stream, sink, times):
        for line in stream:
            if times is not None:
                times.append(time.monotonic())
            sink.append(line.rstrip("\r\n"))

    def wait_for(self, what, predicate):
        deadline = time.monotonic() + WAIT
        while time.monotonic() < deadline:
            if predicate():
                return True
            if self.proc.poll() is not None:
                time.sleep(0.2)  # 行程已結束:讓輸出讀完再看最後一次,不必等到逾時
                if predicate():
                    return True
                fail(self.scenario, f"範例已結束(結束碼 {self.proc.returncode}),卻還沒有:{what}", self)
                return False
            time.sleep(0.05)
        fail(self.scenario, f"等了 {WAIT:.0f} 秒仍沒有:{what}", self)
        return False

    def wait_exit(self, what):
        try:
            code = self.proc.wait(timeout=WAIT)
        except subprocess.TimeoutExpired:
            fail(self.scenario, f"{what}:{WAIT:.0f} 秒內沒有結束", self)
            return None
        time.sleep(0.2)  # 讓輸出讀完
        return code

    def expect(self, ok, text):
        if not ok:
            fail(self.scenario, text, self)
        return ok

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=WAIT)
        time.sleep(0.1)  # 讓輸出讀完
        self.gateway.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


def has(lines, text):
    return any(text in line for line in lines)


def empty(_n, _req):
    return 200, {"messages": []}


def retry_lines(run):
    return [line for line in run.err if "subscribe error" in line]


# ── 0a. 釘版:requirements.txt 第一行就是 lockfile ─────────────────────
# Python 範例沒有 lockfile。第一行寫成範圍(>=、~=)的話,CI 驗的那一版就不是使用者明天裝到的那一版。
def check_requirements():
    name = "requirements"
    lines = (EXAMPLE / "requirements.txt").read_text(encoding="utf-8").splitlines()
    pinned = re.fullmatch(r"msgmesh==(\d+\.\d+\.\d+)", lines[0].strip()) if lines else None
    if not pinned:
        fail(name, f"requirements.txt 第一行必須是 msgmesh==X.Y.Z(確切版本),實際是:{lines[0] if lines else '(空檔)'}")
    else:
        try:
            installed = importlib.metadata.version("msgmesh")
        except importlib.metadata.PackageNotFoundError:
            installed = None
        if installed != pinned.group(1):
            fail(name, f"requirements.txt 釘的是 msgmesh=={pinned.group(1)},這個直譯器裝到的是 {installed}(請用裝過 requirements.txt 的 venv 來跑)")
    # SDK 自己只要求 httpx>=0.27、沒有上限;httpx 1.x 的開發版會讓這一版 SDK 一啟動就 TypeError。
    if not any(re.fullmatch(r"httpx>=[0-9.]+,<1", line.strip()) for line in lines):
        fail(name, "requirements.txt 少了有上限的 httpx 那一行(httpx>=…,<1)")
    try:
        httpx_version = importlib.metadata.version("httpx")
    except importlib.metadata.PackageNotFoundError:
        httpx_version = None
    if httpx_version is None or not httpx_version.startswith("0."):
        fail(name, f"裝到的 httpx 應該是 0.x,實際是 {httpx_version}")


# ── 0b. .env.example 的預設值 ────────────────────────────────────────
# 使用者只需要填 key,靠的是這個檔的另外三行已經是對的。
def check_env_example():
    text = (EXAMPLE / ".env.example").read_text(encoding="utf-8").splitlines()
    for want in (
        f"MSGMESH_GATEWAY_URL={SERVICE_URL}",
        f"MSGMESH_API_KEY={PLACEHOLDER}",
        "MSGMESH_TOPIC=orders",
        f"MSGMESH_GROUP={EXAMPLE.name}",
    ):
        if want not in text:
            fail("env-example", f".env.example 少了這一行(逐字):{want}")


# ── 0c. main.py 內建的服務位址 = .env.example 的位址 ──────────────────
# .env 裡沒有 MSGMESH_GATEWAY_URL 時用的是 main.py 內建的那個。實跑情境一律把位址指到假 gateway
# (不連外),所以內建值只能靜態比對;不比的話它被改成 localhost 也不會有任何情境變紅。
def check_service_url():
    name = "service-url"
    tree = ast.parse((EXAMPLE / ENTRY).read_text(encoding="utf-8"))
    found = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "SERVICE_URL" for t in node.targets)
        and isinstance(node.value, ast.Constant)
    ]
    if found != [SERVICE_URL]:
        fail(name, f"{ENTRY} 頂層應該恰好有一行 SERVICE_URL = \"{SERVICE_URL}\"(與 .env.example 相同),實際找到:{found}")


# ── 1. 正常路徑:收到並印出事件,Ctrl-C 以 0 結束 ─────────────────────
def scenario_happy():
    name = "happy"

    def script(n, _req):
        if n == 1:
            return 200, {
                "messages": [
                    {"partition": 0, "offset": 7, "value": json.dumps({"item": "test-order"}), "room": "vip"},
                    {"partition": 1, "offset": 3, "value": "plain text, not JSON"},
                    {"partition": 0, "offset": 8, "value": json.dumps({"note": "訂單"})},
                ]
            }
        return 200, {"messages": []}

    run = Run(name, script)
    try:
        group = EXAMPLE.name
        line1 = f'{EXAMPLE.name}: subscribing to topic "orders" (group={group})... press Ctrl-C to quit'
        line2 = (
            f"{EXAMPLE.name}: if this group has not read this topic before, it starts from the oldest message "
            "still within the topic's retention, so messages already in the topic arrive first"
        )
        if not run.wait_for("第三則事件", lambda: has(run.out, "orders#0/8")):
            return
        run.expect(run.out[0] == line1, f"第一行應逐字為:{line1}")
        run.expect(run.out[1] == line2, f"第二行應逐字為:{line2}")
        run.expect(has(run.out, 'orders#0/7 room=vip {"item": "test-order"}'), "帶 room 的 JSON 事件沒照格式印出")
        run.expect(has(run.out, "orders#1/3 plain text, not JSON"), "非 JSON 的事件應原樣印出、且不帶 room=")
        run.expect(has(run.out, 'orders#0/8 {"note": "訂單"}'), "含非 ASCII 字元的 JSON 事件應原樣印出(不轉成 \\u 跳脫)")
        first = run.gateway.requests[0]
        run.expect(first["path"] == "/v1/topics/orders/messages", f"請求路徑不對:{first['path']}")
        run.expect(first["params"].get("group") == [group], f"請求的 group 不對:{first['query']}")
        run.expect(first["auth"] == f"Bearer {SMOKE_KEY}", "Authorization 標頭不是 .env 裡的 key")
        run.expect(not run.err, "正常路徑不該有 stderr 輸出")
        run.proc.send_signal(signal.SIGINT)
        code = run.wait_exit("送出 SIGINT 後")
        if code is not None:
            run.expect(code == 0, f"Ctrl-C 之後的結束碼應為 0,實際 {code}")
            run.expect(has(run.out, "Received Ctrl-C, stopping the subscription."), "Ctrl-C 之後沒印出停止訊息")
            run.expect(not has(run.err, "Traceback"), "Ctrl-C 不該噴出 traceback")
    finally:
        run.close()


# ── 2. SIGTERM 也要乾淨結束(docker stop、行程管理器)────────────────
def scenario_sigterm():
    name = "sigterm"
    run = Run(name, empty)
    try:
        if not run.wait_for("至少一次輪詢", lambda: len(run.gateway.requests) >= 1):
            return
        run.proc.send_signal(signal.SIGTERM)
        code = run.wait_exit("送出 SIGTERM 後")
        if code is not None:
            run.expect(code == 0, f"SIGTERM 之後的結束碼應為 0,實際 {code}")
            run.expect(has(run.out, "Received SIGTERM, stopping the subscription."), "SIGTERM 之後沒印出停止訊息")
    finally:
        run.close()


# ── 3. 啟動檢查:設定不可能成功時,印原因、以 1 結束、一個請求都不打 ───
def scenario_refuses_to_start(name, must_mention, key=SMOKE_KEY, dotenv=None):
    run = Run(name, empty, key=key, dotenv=dotenv)
    try:
        code = run.wait_exit("設定有問題時")
        if code is None:
            return
        run.expect(code == 1, f"結束碼應為 1,實際 {code}")
        for text in must_mention:
            run.expect(has(run.err, text), f"錯誤訊息沒提到 {text}")
        run.expect(not run.gateway.requests, "設定有問題時不該送出任何請求")
        run.expect(not has(run.err, "Traceback"), "不該噴出 traceback")
        run.expect(not run.out, "不該印出啟動那兩行")
    finally:
        run.close()


# ── 4. 401 / 403 / 404:印出原因、以 1 結束、不一直重打 ────────────────
def scenario_rejected(status, body, must_mention):
    name = f"http-{status}"
    run = Run(name, lambda _n, _req: (status, body))
    try:
        code = run.wait_exit(f"gateway 一律回 {status} 時")
        if code is None:
            return
        run.expect(code == 1, f"結束碼應為 1,實際 {code}")
        run.expect(has(run.err, f"HTTP {status}"), f"錯誤訊息沒寫出 HTTP {status}")
        run.expect(has(run.err, must_mention), f"錯誤訊息沒提到 {must_mention}")
        run.expect(has(run.err, body["error"]), "伺服器回的錯誤原文沒印出來")
        run.expect(len(run.gateway.requests) <= 2, f"應該很快放棄,實際打了 {len(run.gateway.requests)} 次")
        run.expect(not has(run.err, "Traceback"), "不該噴出 traceback")
        run.expect(not has(run.err, "environment variable"), "key 來自 .env 時不該出現「key 來自環境變數」那一句")
    finally:
        run.close()


# ── 5. key 被拒、而且用的是環境變數裡的 key(不是 .env 的)→ 多印一句 ──
# README 教人在另一個終端 export .env 的內容;之後在那個終端改 .env 重跑,用的仍是舊 key。
def scenario_rejected_env_key():
    name = "rejected-env-key"
    body = {"error": "forbidden: capability denies this op on this topic"}
    run = Run(name, lambda _n, _req: (403, body), environ=lambda _gw: {"MSGMESH_API_KEY": OTHER_KEY})
    try:
        code = run.wait_exit("gateway 一律回 403 時")
        if code is None:
            return
        run.expect(code == 1, f"結束碼應為 1,實際 {code}")
        run.expect(run.gateway.requests[0]["auth"] == f"Bearer {OTHER_KEY}", "送出的應該是環境變數裡的 key")
        run.expect(
            has(run.err, "MSGMESH_API_KEY environment variable, not from .env"),
            "key 來自環境變數且與 .env 不同時,應多印一句說明",
        )
    finally:
        run.close()


# ── 6. 其他錯誤:不結束,SDK 重試後照樣收到;同一種錯誤不洗版 ──────────
def scenario_transient():
    name = "transient"

    def script(n, _req):
        if n <= 2:
            return 500, {"error": "internal server error", "request_id": f"req-{n}"}
        if n == 3:
            return 503, {"error": "service unavailable"}
        if n == 4:
            return 200, {"messages": [{"partition": 0, "offset": 1, "value": json.dumps({"after": "retry"})}]}
        return 200, {"messages": []}

    run = Run(name, script)
    try:
        if not run.wait_for("重試之後的事件", lambda: has(run.out, "orders#0/1")):
            return
        run.expect(run.proc.poll() is None, "暫時性錯誤不該讓範例結束")
        lines = retry_lines(run)
        run.expect(
            len(lines) == 2 and "HTTP 500" in lines[0] and "HTTP 503" in lines[1],
            f"兩次 500 加一次 503 應印兩行(同一種只印一次、不同種各印一次),實際 {len(lines)} 行",
        )
        run.expect(
            bool(lines) and "MsgMeshError" in lines[0] and run.gateway.url in lines[0],
            "錯誤那一行應帶例外類別與 gateway 位址",
        )
    finally:
        run.close()


# ── 7. 節流以時間為準:同一種錯誤隔一段時間會再印一次,並附累計次數 ────
# 只印第一次的話,安靜的 topic 上第二次斷線會完全沒有聲音。
# main.py 的間隔是 30 秒;這裡先確認那一行逐字存在,再把副本改成 3 秒來跑,免得每次冒煙多等半分鐘。
def scenario_throttle():
    name = "throttle"
    short = 3

    def patch(text):
        if text.count(REPEAT_LINE) != 1:
            fail(name, f"{ENTRY} 裡應該恰好有一行:{REPEAT_LINE}")
        return text.replace(REPEAT_LINE, f"ERROR_REPEAT_SECONDS = {short}")

    run = Run(name, lambda _n, _req: (500, {"error": "internal server error"}), patch=patch)
    try:
        if not run.wait_for("第二行 subscribe error", lambda: len(retry_lines(run)) >= 2):
            return
        lines = retry_lines(run)
        times = [at for at, line in zip(run.err_at, run.err) if "subscribe error" in line]
        gap = times[1] - times[0]
        run.expect(gap >= short - 0.5, f"同一種錯誤應隔約 {short} 秒才再印,實際隔 {gap:.1f} 秒")
        run.expect("errors of this kind so far" not in lines[0], "第一行不該有累計次數")
        count = re.search(r"(\d+) errors of this kind so far", lines[1])
        run.expect(bool(count) and int(count.group(1)) >= 3, "第二行應附累計次數(此時至少 3 次)")
        run.expect(run.proc.poll() is None, "持續的 500 不該讓範例結束")
    finally:
        run.close()


# ── 8. 預設值:.env 只有 key 一行,其餘用 main.py 內建的 ───────────────
# 其他情境都拿完整的 .env.example 當 .env,main.py 內建的 topic / group 預設值一次也不會被用到。
# 位址由環境變數給(不能讓它去連內建的正式位址;內建位址由上面的 check_service_url 靜態比對)。
def scenario_defaults():
    name = "defaults"
    run = Run(
        name,
        empty,
        dotenv=lambda _gw: f"MSGMESH_API_KEY={SMOKE_KEY}\n",
        environ=lambda gw: {"MSGMESH_GATEWAY_URL": gw.url},
    )
    try:
        if not run.wait_for("至少一次輪詢", lambda: len(run.gateway.requests) >= 1):
            return
        first = run.gateway.requests[0]
        run.expect(first["path"] == "/v1/topics/orders/messages", f"預設 topic 應為 orders,請求路徑是:{first['path']}")
        run.expect(first["params"].get("group") == [EXAMPLE.name], f"預設 group 應為 {EXAMPLE.name}:{first['query']}")
        run.expect(first["auth"] == f"Bearer {SMOKE_KEY}", "Authorization 標頭不是 .env 裡的 key")
    finally:
        run.close()


# ── 9. 環境變數優先於 .env(與 Node 的 --env-file 相同)────────────────
def scenario_env_wins():
    name = "env-wins"
    run = Run(
        name,
        empty,
        environ=lambda _gw: {"MSGMESH_TOPIC": "from-env", "MSGMESH_GROUP": "group-from-env", "MSGMESH_API_KEY": OTHER_KEY},
    )
    try:
        if not run.wait_for("至少一次輪詢", lambda: len(run.gateway.requests) >= 1):
            return
        first = run.gateway.requests[0]
        run.expect(first["path"] == "/v1/topics/from-env/messages", f"環境變數的 topic 應優先於 .env:{first['path']}")
        run.expect(first["params"].get("group") == ["group-from-env"], f"環境變數的 group 應優先於 .env:{first['query']}")
        run.expect(first["auth"] == f"Bearer {OTHER_KEY}", "環境變數的 key 應優先於 .env")
    finally:
        run.close()


# ── 10. .env 的幾種寫法:開頭有 BOM、行首有 export、值有引號 ───────────
def scenario_env_file_forms():
    name = "env-file-forms"
    run = Run(
        name,
        empty,
        dotenv=lambda gw: (
            f'﻿export MSGMESH_API_KEY="{SMOKE_KEY}"\n' f"MSGMESH_GATEWAY_URL='{gw.url}'\n"
        ),
    )
    try:
        if not run.wait_for("至少一次輪詢(BOM、export、引號都要處理掉才到得了這裡)", lambda: len(run.gateway.requests) >= 1):
            return
        run.expect(run.gateway.requests[0]["auth"] == f"Bearer {SMOKE_KEY}", "key 的引號沒去掉,或讀到的不是那一行")
    finally:
        run.close()


# ── 11. 處理函式丟例外:印 traceback,同一批後面的訊息照樣處理 ─────────
# SDK 0.6.0 的實際行為(實測):handler 丟出例外時,SDK 把它交給 on_error,同一批剩下的訊息不再處理、
# 也不會重送。main.py 在自己的 on_message 裡接住例外,就是為了不讓一則壞訊息拖掉同批其餘的。
# 這裡讓第二則的 value 不是字串(真的 gateway 不會這樣),範例的 handle_event 會因此丟 TypeError。
def scenario_handler_error():
    name = "handler-error"

    def script(n, _req):
        if n == 1:
            return 200, {
                "messages": [
                    {"partition": 0, "offset": 1, "value": json.dumps({"seq": 1})},
                    {"partition": 0, "offset": 2, "value": 123},
                    {"partition": 0, "offset": 3, "value": json.dumps({"seq": 3})},
                ]
            }
        return 200, {"messages": []}

    run = Run(name, script)
    try:
        if not run.wait_for("丟例外那一則之後的事件", lambda: has(run.out, "orders#0/3")):
            return
        run.expect(has(run.out, "orders#0/1"), "丟例外之前的那一則沒印出")
        run.expect(not has(run.out, "orders#0/2"), "這個情境靠第二則讓 handle_event 丟例外;它被印出來代表情境失效了")
        run.expect(has(run.err, "Traceback") and has(run.err, "TypeError"), "處理函式的例外應印出 traceback")
        run.expect(not retry_lines(run), "處理函式的例外不該被當成 subscribe error")
        run.expect(run.proc.poll() is None, "處理函式的例外不該讓範例結束")
    finally:
        run.close()


def main():
    if not (EXAMPLE / ENTRY).is_file() or not (EXAMPLE / ".env.example").is_file():
        raise SystemExit(f"✗ 請在範例目錄底下執行(找不到 {ENTRY} 或 .env.example):{EXAMPLE}")
    check_requirements()
    check_env_example()
    check_service_url()
    scenario_happy()
    scenario_sigterm()
    scenario_refuses_to_start("missing-key", ["MSGMESH_API_KEY"], key=PLACEHOLDER)
    scenario_refuses_to_start("key-not-ascii", ["MSGMESH_API_KEY", "ASCII"], key=SMOKE_KEY + "…")
    scenario_refuses_to_start(
        "url-without-scheme",
        ["MSGMESH_GATEWAY_URL", "https://"],
        dotenv=lambda gw: f"MSGMESH_API_KEY={SMOKE_KEY}\nMSGMESH_GATEWAY_URL={gw.host}\n",
    )
    scenario_refuses_to_start(
        "env-not-utf8",
        ["UTF-8"],
        dotenv=lambda gw: env_from_example(SMOKE_KEY, gw.url).encode("utf-16"),
    )
    scenario_rejected(401, {"error": "invalid api key"}, "MSGMESH_API_KEY")
    scenario_rejected(403, {"error": "forbidden: capability denies this op on this topic"}, "capability")
    scenario_rejected(404, {"error": "topic not found"}, "MSGMESH_TOPIC")
    scenario_rejected_env_key()
    scenario_transient()
    scenario_throttle()
    scenario_defaults()
    scenario_env_wins()
    scenario_env_file_forms()
    scenario_handler_error()
    if failures:
        print(f"\n✗ {EXAMPLE.name}:{len(failures)} 項未通過({', '.join(sorted(set(failures)))})")
        return 1
    print(f"✓ {EXAMPLE.name}:實跑冒煙全部通過(Python {sys.version.split()[0]},msgmesh {importlib.metadata.version('msgmesh')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
