# py-run-smoke —— 把 Python 範例真的跑起來,對一個本機的假 gateway 收訊息。
#
# 為什麼需要它:py_compile 只證明語法過得去;「裝得起來」也不代表「跑起來會收到東西」。
# JS 範例在 CI 裡沒辦法連線,只能做靜態的 api-smoke;Python 範例只打一支 HTTP 端點
# (GET /v1/topics/{topic}/messages),假得起來,所以這裡直接跑。不需要任何憑證,不連外。
#
# 「不連外」是做出來的,不是假設:每個子行程的 HTTP(S)_PROXY 都指到本機的一個攔截點(Tripwire),
# 它只記下請求的第一行、回 502 就斷線。範例的 .env 讀取壞掉時,位址會落回 main.py 內建的正式位址,
# 那個連線會在攔截點結束,不會帶著假 key 真的打出去;而且那個情境會因為「試圖連外」變紅。
#
# 守的東西(每個情境各自寫在下面):
#   · requirements.txt 第一行是確切版本的 msgmesh,而且裝到的就是那一版;裝到的 SDK 自己給了 httpx 上限,
#     裝到的 httpx 是 0.x
#   · 照 README 的做法(.env.example 複製成 .env、只改 key)啟動得了,而且真的收到並印出事件
#   · 啟動時印的兩行、預設 topic / group / 服務位址、Authorization 標頭、環境變數優先於 .env
#   · key 沒填(空字串與佔位值各一)/ 含非 ASCII 字元 / 含空白或控制字元、位址沒有 http(s)://、
#     .env 不是 UTF-8(含沒有 BOM 的 UTF-16)或讀不了 → 印原因後結束,不打任何請求,不噴 traceback
#   · 400 / 401 / 403 / 404 → 印出原因後以 1 結束(SDK 在 401 會停止輪詢,範例不結束就是無聲卡死)
#   · 錯誤文字裡出現 key 的值時遮成 ***
#   · 其他錯誤 → 不結束、SDK 重試後照樣收得到;同一種錯誤不洗版,但隔一段時間會再印一次
#   · 處理函式丟例外 → 同一批後面的訊息照樣處理
#   · Ctrl-C(SIGINT)與 SIGTERM → 以 0 結束;結束前等手上那一則處理完,之後不再印任何東西
#   · stdout 被關掉(`python main.py | head -1`)→ 安靜地結束,不噴 traceback
#   · 沒設位址時用的是內建的正式位址(由攔截點看到那個主機名),而且連不出去
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
import socketserver
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
skipped = []


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


class Tripwire:
    """子行程的對外代理。任何不是連 127.0.0.1 / localhost 的請求都會到這裡:記下第一行、回 502、斷線。"""

    def __init__(self):
        self.hits = []
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    first = self.rfile.readline(4096).decode("latin-1").strip()
                    outer.hits.append(first or "(空連線)")
                    self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                except OSError:
                    pass

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self._server = Server(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()


TRIPWIRE = Tripwire()


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
    dotenv_mode 是 .env 的檔案權限;stdout_lines 是「讀幾行 stdout 之後就把讀端關掉」(模擬 | head -N)。
    may_reach_out=True 表示這個情境本來就預期範例會往外連(由攔截點接住),其餘情境一有就紅。
    """

    def __init__(self, scenario, script, key=SMOKE_KEY, dotenv=None, environ=None, patch=None,
                 dotenv_mode=None, stdout_lines=None, may_reach_out=False):
        self.scenario = scenario
        self.may_reach_out = may_reach_out
        self.hits_before = len(TRIPWIRE.hits)
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
        if dotenv_mode is not None:
            (self.copy / ".env").chmod(dotenv_mode)
        if patch:
            entry = self.copy / ENTRY
            entry.write_text(patch(entry.read_text(encoding="utf-8")), encoding="utf-8")
        # 環境裡的 MSGMESH_* 一律拿掉:設定只能來自剛寫好的 .env(與情境自己給的變數),否則測不到讀檔那段。
        # PYTHONUNBUFFERED 也拿掉:它會蓋掉「輸出有沒有即時送出」這件事。
        env = {k: v for k, v in os.environ.items() if not k.startswith("MSGMESH_") and k != "PYTHONUNBUFFERED"}
        # 絕不連外:往 127.0.0.1 / localhost 以外的連線一律走攔截點(見檔頭)。大小寫都設,各家 HTTP client 認的不同。
        for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
            env[name] = env[name.lower()] = TRIPWIRE.url
        env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
        if environ:
            env.update(environ(self.gateway))
        # cwd 刻意不是範例目錄:.env 必須是從腳本所在位置找到的。
        # preexec_fn:把 SIGINT 的處置還原成預設。這支腳本被放到背景跑(shell 的 &、nohup)時 SIGINT 是「忽略」,
        # 子行程會繼承下去,Python 就不會裝 KeyboardInterrupt 的處理,Ctrl-C 的情境會白等到逾時。
        self.proc = subprocess.Popen(
            [sys.executable, str(self.copy / ENTRY)],
            cwd=str(self.tmp),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),
        )
        self.out, self.err, self.err_at = [], [], []
        self._pumps = [
            threading.Thread(target=self._pump, args=(self.proc.stdout, self.out, None, stdout_lines), daemon=True),
            threading.Thread(target=self._pump, args=(self.proc.stderr, self.err, self.err_at, None), daemon=True),
        ]
        for pump in self._pumps:
            pump.start()

    @staticmethod
    def _pump(stream, sink, times, close_after):
        for line in stream:
            if times is not None:
                times.append(time.monotonic())
            sink.append(line.rstrip("\r\n"))
            if close_after is not None and len(sink) >= close_after:
                stream.close()  # 讀端關掉:範例下一次寫 stdout 會拿到 EPIPE
                return

    def _drain(self):
        """行程結束後,等兩條讀取執行緒把剩下的輸出讀完(管線關閉就會結束),再做斷言。"""
        for pump in self._pumps:
            pump.join(timeout=WAIT)

    def first_request(self):
        """假 gateway 收到的第一個請求;一個都沒有就記一筆失敗並回 None(範例壞掉時要的是斷言失敗,不是這支腳本自己中止)。"""
        if not self.gateway.requests:
            fail(self.scenario, "假 gateway 沒有收到任何請求", self)
            return None
        return self.gateway.requests[0]

    def wait_for(self, what, predicate):
        deadline = time.monotonic() + WAIT
        while time.monotonic() < deadline:
            if predicate():
                return True
            if self.proc.poll() is not None:
                self._drain()  # 行程已結束:輸出讀完再看最後一次,不必等到逾時
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
        self._drain()
        return code

    def expect(self, ok, text):
        if not ok:
            fail(self.scenario, text, self)
        return ok

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=WAIT)
        self._drain()
        for stream in (self.proc.stdout, self.proc.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        reached_out = TRIPWIRE.hits[self.hits_before:]
        if reached_out and not self.may_reach_out:
            fail(
                self.scenario,
                f"範例試圖連到本機以外的位址(已被攔下,沒有送出去):{reached_out[:3]} —— 多半是位址沒有從 .env 或環境讀到,落回了內建的正式位址",
                self,
            )
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
    # httpx 的上限:SDK 0.7.0 起自己宣告(httpx>=0.27,<1),requirements.txt 不必再寫一行。更早的 SDK
    # 沒有上限,而 httpx 1.x 的開發版會讓它一建立 client 就 TypeError。這裡讀裝到的 SDK 的依賴宣告:
    # 把第一行釘回沒有上限的舊版、或日後的 SDK 把上限拿掉時,這一項會紅(到時候要先對新的 httpx 實跑)。
    try:
        sdk_requires = importlib.metadata.requires("msgmesh") or []
    except importlib.metadata.PackageNotFoundError:
        sdk_requires = []
    httpx_specs = [r.split(";")[0] for r in sdk_requires if re.match(r"httpx(?![\w.-])", r) and "extra ==" not in r]
    if not any(re.search(r"<\s*1(?:\.0)*\s*(?:,|$)", spec) for spec in httpx_specs):
        fail(name, f"裝到的 msgmesh 沒有給 httpx 版本上限(<1),它宣告的是:{httpx_specs or '(沒有 httpx 這一項)'}")
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
        first = run.first_request()
        if first is None:
            return
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
# secret:這個情境的 key 裡「真正像 key 的那一段」;給了就斷言它不出現在任何輸出裡。
def scenario_refuses_to_start(name, must_mention, key=SMOKE_KEY, dotenv=None, environ=None, dotenv_mode=None, secret=None):
    run = Run(name, empty, key=key, dotenv=dotenv, environ=environ, dotenv_mode=dotenv_mode)
    try:
        code = run.wait_exit("設定有問題時")
        if code is None:
            return
        run.expect(code == 1, f"結束碼應為 1,實際 {code}")
        for text in must_mention:
            run.expect(has(run.err, text), f"錯誤訊息沒提到 {text}")
        if secret:
            run.expect(not has(run.out + run.err, secret), "輸出裡不該出現 key 的值")
        run.expect(not run.gateway.requests, "設定有問題時不該送出任何請求")
        run.expect(not has(run.err, "Traceback"), "不該噴出 traceback")
        run.expect(not run.out, "不該印出啟動那兩行")
    finally:
        run.close()


# ── 4. 400 / 401 / 403 / 404:印出原因、以 1 結束、不一直重打 ──────────
# 400:topic 名稱不合法(.env 行尾加了註解就會這樣),同一個請求重打一百次也不會成功。
# 404:只有開了嚴格 topic 的帳號、或位址指到別的服務才會遇到,所以訊息要帶上目前的位址。
def scenario_rejected(status, body, must_mention, max_requests=2):
    name = f"http-{status}"
    run = Run(name, lambda _n, _req: (status, body))
    try:
        code = run.wait_exit(f"gateway 一律回 {status} 時")
        if code is None:
            return
        run.expect(code == 1, f"結束碼應為 1,實際 {code}")
        run.expect(has(run.err, f"HTTP {status}"), f"錯誤訊息沒寫出 HTTP {status}")
        for text in [must_mention] if isinstance(must_mention, str) else must_mention:
            run.expect(has(run.err, text.replace("{gateway}", run.gateway.url)), f"錯誤訊息沒提到 {text}")
        run.expect(has(run.err, body["error"]), "伺服器回的錯誤原文沒印出來")
        run.expect(
            1 <= len(run.gateway.requests) <= max_requests,
            f"應該送出請求、而且很快放棄(至多 {max_requests} 個),實際打了 {len(run.gateway.requests)} 次",
        )
        run.expect(not has(run.err, "Traceback"), "不該噴出 traceback")
        run.expect(not has(run.err, "environment variable"), "key 來自 .env 時不該出現「key 來自環境變數」那一句")
    finally:
        run.close()


# ── 5. key 被拒、而且用的是環境變數裡的 key(不是 .env 的)→ 多印一句 ──
# README 教人在另一個終端 export .env 的內容;之後在那個終端改 .env 重跑,用的仍是舊 key。
# .env 裡的 key 是空的或仍是佔位值時,那一句不能叫人「改用 .env 的 key」(照做只會得到 Missing MSGMESH_API_KEY)。
def scenario_rejected_env_key(name="rejected-env-key", key_in_file=SMOKE_KEY):
    body = {"error": "forbidden: capability denies this op on this topic"}
    run = Run(name, lambda _n, _req: (403, body), key=key_in_file, environ=lambda _gw: {"MSGMESH_API_KEY": OTHER_KEY})
    try:
        code = run.wait_exit("gateway 一律回 403 時")
        if code is None:
            return
        run.expect(code == 1, f"結束碼應為 1,實際 {code}")
        first = run.first_request()
        if first is None:
            return
        run.expect(first["auth"] == f"Bearer {OTHER_KEY}", "送出的應該是環境變數裡的 key")
        run.expect(has(run.err, "MSGMESH_API_KEY environment variable"), "key 來自環境變數時,應多印一句說明")
        usable = key_in_file not in ("", PLACEHOLDER)
        run.expect(
            has(run.err, "not from .env") == usable and has(run.err, "to use the key in .env") == usable,
            "「改用 .env 的 key」只該在 .env 裡真的有 key 時出現" if not usable else "key 與 .env 不同時,應說明目前用的不是 .env 的、以及怎麼改用 .env 的",
        )
        if not usable:
            run.expect(has(run.err, "the one in .env is not filled in"), ".env 沒填 key 時,那一句應說明 .env 裡的沒填")
    finally:
        run.close()


# ── 5b. 錯誤文字裡有 key 的值 → 遮成 *** ──────────────────────────────
# 函式庫的錯誤訊息可能引用請求內容(審查實測過:key 尾端帶換行時,例外訊息把整個 Authorization 標頭印出來)。
# 這裡讓假 gateway 把收到的 key 原樣放進錯誤訊息,走「會結束」與「會重試」兩條印訊息的路。
def scenario_key_redacted(name, status):
    run = Run(name, lambda _n, req: (status, {"error": f"rejected credential {req['auth']}"}))
    try:
        if not run.wait_for("錯誤訊息", lambda: has(run.err, "rejected credential")):
            return
        run.expect(has(run.err, "rejected credential Bearer ***"), "錯誤文字裡的 key 應遮成 ***")
        run.expect(not has(run.out + run.err, SMOKE_KEY), "輸出裡不該出現 key 的值")
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
        first = run.first_request()
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
        first = run.first_request()
        run.expect(first["path"] == "/v1/topics/from-env/messages", f"環境變數的 topic 應優先於 .env:{first['path']}")
        run.expect(first["params"].get("group") == ["group-from-env"], f"環境變數的 group 應優先於 .env:{first['query']}")
        run.expect(first["auth"] == f"Bearer {OTHER_KEY}", "環境變數的 key 應優先於 .env")
    finally:
        run.close()


# ── 10. .env 的幾種寫法:開頭有 BOM、行首有 export、值有引號、一行沒有名稱的 =foo ──
# BOM 用跳脫寫法:寫成看不見的字面字元的話,被編輯器或格式化工具吃掉後這道守門會無聲消失。
def scenario_env_file_forms():
    name = "env-file-forms"
    run = Run(
        name,
        empty,
        dotenv=lambda gw: (
            f'\ufeffexport MSGMESH_API_KEY="{SMOKE_KEY}"\n' f"=foo\nMSGMESH_GATEWAY_URL='{gw.url}'\n"
        ),
    )
    try:
        if not run.wait_for("至少一次輪詢(BOM、export、引號、=foo 都要處理掉才到得了這裡)", lambda: len(run.gateway.requests) >= 1):
            return
        run.expect(run.first_request()["auth"] == f"Bearer {SMOKE_KEY}", "key 的引號沒去掉,或讀到的不是那一行")
        run.expect(not has(run.err, "Traceback"), "不該噴出 traceback")
    finally:
        run.close()


# ── 11. 處理函式丟例外:印 traceback,同一批後面的訊息照樣處理 ─────────
# SDK 0.7.0 的實際行為(實測;0.6.0 相同):handler 丟出例外時,SDK 把它交給 on_error,同一批剩下的訊息不再處理、
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


# ── 12. 結束前等手上那一則處理完,之後不再印任何東西 ───────────────────
# 審查在訊息洪流中送 SIGTERM,出現過一次 Fatal Python error(結束碼 -6):主執行緒收尾時,SDK 的背景執行緒
# 正握著 stdout 的鎖。main.py 的做法是兩邊都在同一把鎖裡印、主執行緒拿到鎖才結束。
# 那個崩潰本身重現不出來(審查 200 次 1 次),這裡守的是它的兩個可觀察後果:
#   · 處理到一半時收到 SIGTERM:那一則照樣印完,而且印在停止訊息之前(副本裡讓 handle_event 先睡 1 秒);
#   · 訊息洪流中收到 SIGTERM:結束碼 0、停止訊息是 stdout 的最後一行、stderr 是空的。
HANDLE_LINE = "    room = f\" room={msg.room}\" if msg.room else \"\""


def scenario_exit_waits_for_handler():
    name = "exit-waits-for-handler"

    def patch(text):
        if text.count(HANDLE_LINE) != 1:
            fail(name, f"{ENTRY} 的 handle_event 裡應該恰好有一行:{HANDLE_LINE.strip()}")
        return text.replace(HANDLE_LINE, "    time.sleep(1.0)\n" + HANDLE_LINE)

    def script(n, _req):
        if n == 1:
            return 200, {"messages": [{"partition": 0, "offset": 1, "value": json.dumps({"slow": 1})}]}
        return 200, {"messages": []}

    run = Run(name, script, patch=patch)
    try:
        if not run.wait_for("第一次輪詢", lambda: len(run.gateway.requests) >= 1):
            return
        time.sleep(0.3)  # 這時 handle_event 正在睡
        run.expect(not has(run.out, "orders#0/1"), "這個情境要在處理到一半時送訊號;事件已經印出來代表情境失效了")
        run.proc.send_signal(signal.SIGTERM)
        code = run.wait_exit("送出 SIGTERM 後")
        if code is None:
            return
        run.expect(code == 0, f"結束碼應為 0,實際 {code}")
        event = [i for i, line in enumerate(run.out) if "orders#0/1" in line]
        stopped = [i for i, line in enumerate(run.out) if "Received SIGTERM" in line]
        run.expect(bool(event), "處理到一半的那一則應該印完才結束")
        run.expect(bool(event) and bool(stopped) and event[0] < stopped[0], "那一則應印在停止訊息之前")
        run.expect(not run.err, "不該有 stderr 輸出")
    finally:
        run.close()


def flood(_n, _req):
    return 200, {"messages": [{"partition": 0, "offset": i, "value": json.dumps({"i": i})} for i in range(200)]}


def scenario_flood_sigterm():
    name = "flood-sigterm"
    run = Run(name, flood)
    try:
        if not run.wait_for("至少 1000 行事件", lambda: len(run.out) >= 1000):
            return
        run.proc.send_signal(signal.SIGTERM)
        code = run.wait_exit("洪流中送出 SIGTERM 後")
        if code is None:
            return
        run.expect(code == 0, f"結束碼應為 0,實際 {code}")
        run.expect(bool(run.out) and run.out[-1] == "Received SIGTERM, stopping the subscription.", "停止訊息應是 stdout 的最後一行")
        run.expect(not run.err, "不該有 stderr 輸出(Fatal Python error 會出現在這裡)")
    finally:
        run.close()


# ── 13. stdout 被關掉(python main.py | head -3)→ 安靜地結束 ─────────
# 沒處理的話,每則訊息噴一份 BrokenPipeError 的 traceback,行程也不結束。
def scenario_stdout_closed():
    name = "stdout-closed"
    run = Run(name, flood, stdout_lines=3)
    try:
        code = run.wait_exit("stdout 的讀端關閉後")
        if code is None:
            return
        run.expect(code == 1, f"結束碼應為 1,實際 {code}")
        run.expect(not run.err, "stdout 被關掉時不該在 stderr 印任何東西(尤其是 traceback)")
        seen = len(run.gateway.requests)
        time.sleep(0.3)
        run.expect(len(run.gateway.requests) == seen, "行程結束後不該還有請求")
    finally:
        run.close()


# ── 14. 沒設位址時用內建的正式位址 —— 而且連不出去 ────────────────────
# 兩種走法都會讓範例朝內建位址去:(a) .env 只有 key、環境也沒有位址(README 寫的預設行為);
# (b) 範例根本不讀 .env(把副本改壞)、key 由環境給 —— 審查跑這種變異時,冒煙真的帶著假 key 打到了正式環境。
# 兩種都必須:由攔截點接住、看到的主機名就是內建位址、假 gateway 一個請求都沒有。
# 這同時是這支腳本「不連外」的自我檢查:攔截點沒看到連線,代表代理設定沒有生效,後面的情境就沒有保護。
READ_ENV_LINE = '    FILE_VALUES = read_env_file(Path(__file__).resolve().parent / ".env")'


def scenario_no_egress(name, unread_env):
    def patch(text):
        if text.count(READ_ENV_LINE) != 1:
            fail(name, f"{ENTRY} 裡應該恰好有一行:{READ_ENV_LINE.strip()}")
        return text.replace(READ_ENV_LINE, "    FILE_VALUES = {}")

    if unread_env:
        run = Run(name, empty, patch=patch, environ=lambda _gw: {"MSGMESH_API_KEY": OTHER_KEY}, may_reach_out=True)
    else:
        run = Run(name, empty, dotenv=lambda _gw: f"MSGMESH_API_KEY={SMOKE_KEY}\n", may_reach_out=True)
    try:
        host = urlsplit(SERVICE_URL).netloc
        if not run.wait_for("連線被攔下後的錯誤訊息", lambda: bool(retry_lines(run))):
            return
        hits = TRIPWIRE.hits[run.hits_before:]
        run.expect(bool(hits) and all(hit.startswith(f"CONNECT {host}:443") for hit in hits), f"攔截點應只看到 CONNECT {host}:443,實際:{hits[:3]}")
        run.expect(f"from {SERVICE_URL};" in retry_lines(run)[0], f"錯誤那一行應寫出內建位址 {SERVICE_URL}")
        run.expect(not run.gateway.requests, "假 gateway 不該收到請求(位址不是它)")
        run.expect(run.proc.poll() is None, "連不上不該讓範例結束")
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
    scenario_refuses_to_start("missing-key", ["Missing MSGMESH_API_KEY"], key=PLACEHOLDER)
    scenario_refuses_to_start("empty-key", ["Missing MSGMESH_API_KEY"], key="")
    scenario_refuses_to_start("key-not-ascii", ["MSGMESH_API_KEY", "ASCII"], key=SMOKE_KEY + "…", secret=SMOKE_KEY)
    # .env 的值前後空白會被去掉,所以尾端帶換行 / tab 的 key 只能從環境變數來(例如 export KEY="$(cat file)" 的變體)。
    scenario_refuses_to_start(
        "key-with-newline",
        ["MSGMESH_API_KEY", "whitespace or a control character"],
        environ=lambda _gw: {"MSGMESH_API_KEY": OTHER_KEY + "\n"},
        secret=OTHER_KEY,
    )
    scenario_refuses_to_start(
        "key-with-tab",
        ["MSGMESH_API_KEY", "whitespace or a control character"],
        environ=lambda _gw: {"MSGMESH_API_KEY": "\t" + OTHER_KEY},
        secret=OTHER_KEY,
    )
    scenario_refuses_to_start(
        "key-with-space",
        ["MSGMESH_API_KEY", "whitespace or a control character"],
        key="smoke-key not-a-real-credential",
        secret="not-a-real-credential",
    )
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
    # 沒有 BOM 的 UTF-16:當成 UTF-8 解得開,只是每個字元後面多一個 NUL。
    scenario_refuses_to_start(
        "env-utf16-no-bom",
        ["UTF-8"],
        dotenv=lambda gw: env_from_example(SMOKE_KEY, gw.url).encode("utf-16-le"),
    )
    if os.geteuid() == 0:
        skipped.append("env-unreadable(以 root 執行時任何檔都讀得到,測不出來)")
    else:
        scenario_refuses_to_start("env-unreadable", [".env could not be read"], dotenv_mode=0o000)
    scenario_rejected(400, {"error": "invalid topic name"}, ["MSGMESH_TOPIC", "comment"], max_requests=1)
    scenario_rejected(401, {"error": "invalid api key"}, "MSGMESH_API_KEY")
    scenario_rejected(403, {"error": "forbidden: capability denies this op on this topic"}, "capability")
    scenario_rejected(404, {"error": "topic not found; create it first"}, ["MSGMESH_TOPIC", "{gateway} answered", "strict topics", "MSGMESH_GATEWAY_URL"])
    scenario_rejected_env_key()
    scenario_rejected_env_key("rejected-env-key-file-empty", key_in_file="")
    scenario_rejected_env_key("rejected-env-key-file-placeholder", key_in_file=PLACEHOLDER)
    scenario_key_redacted("key-redacted-exit", 401)
    scenario_key_redacted("key-redacted-retry", 500)
    scenario_transient()
    scenario_throttle()
    scenario_defaults()
    scenario_env_wins()
    scenario_env_file_forms()
    scenario_handler_error()
    scenario_exit_waits_for_handler()
    scenario_flood_sigterm()
    scenario_stdout_closed()
    scenario_no_egress("default-url-no-egress", unread_env=False)
    scenario_no_egress("unread-env-no-egress", unread_env=True)
    for note in skipped:
        print(f"· 略過(略過不等於通過):{note}")
    if failures:
        print(f"\n✗ {EXAMPLE.name}:{len(failures)} 項未通過({', '.join(sorted(set(failures)))})")
        return 1
    print(f"✓ {EXAMPLE.name}:實跑冒煙全部通過(Python {sys.version.split()[0]},msgmesh {importlib.metadata.version('msgmesh')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
