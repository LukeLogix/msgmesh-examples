# msgmesh-examples — MsgMesh 官方範例集

**MsgMesh**(多租戶事件總線)的官方範例／樣板集合。每個資料夾都是「`clone` 就能跑」的最小起手式,示範如何用官方 SDK(npm 的 [`@msgmesh/sdk`](https://www.npmjs.com/package/@msgmesh/sdk)、PyPI 的 [`msgmesh`](https://pypi.org/project/msgmesh/))接入:`chat-web` 在瀏覽器收發即時事件,兩個 `agent-notifier` 腳本(Node 與 Python)只收不發、走長輪詢。

## 現有範例
- `agent-notifier/` — Node 腳本:用 SDK `subscribe()` 訂閱 topic、收到事件就處理(給 AI agent / 後端的事件監看層)。
- `agent-notifier-python/` — `agent-notifier` 的 Python 版:用 PyPI `msgmesh` 的 `subscribe()`,`.env` 由 `main.py` 自己讀(標準函式庫),依賴以 `requirements.txt` 釘住。正常路徑與 Node 版相同,差別列在它的 README;最低 Python 3.9(macOS 的 `/usr/bin/python3` 就是這一版,它來自 Xcode Command Line Tools,不是系統內建),**不得用 3.10 之後才有的語法**。
- `chat-web/` — 網頁聊天室(Vite),附**最小 token-broker 後端**(`server.js` 持 key、向平台鑄 5 分鐘降權 token),前端零長期 key;示範 SSE/WS 收發與多房間(room)隔離。

## 給貢獻者 / AI 助手的準則
- 每個範例維持**零內部依賴**:只用**公開 SDK 與對外介面**(SSE / HTTP / MCP),不假設任何私有服務細節。
- 範例要能只填 **gateway / realtime URL + 一把 API key** 就跑起來;**切勿**把真實金鑰、內部主機 / 網域、部署細節寫進程式碼或文件(這是公開 repo)。
- SDK 用法以 npm 上的 `@msgmesh/sdk`(及 PyPI 的 `msgmesh`)公開 API 為準;範例是**消費端**,發現 SDK 問題回報上游而非在此 fork 契約。
- 每個範例目錄自帶**雙語 README**:`README.md`(英文,GitHub/npm 預設門面,面向國際開發者)+ `README.zh.md`(繁中),兩份頂部互相切換連結(`**English** | [繁體中文](./README.zh.md)` ↔ `[English](./README.md) | **繁體中文**`)。**新增範例時中英兩份一起加**(勿只加單語,否則破壞雙語結構);內容含說明、需要的環境變數、跑法。

- **每個 Node 範例目錄要有 `.ci-expect.json`**(CI 讀它,見下)。新增 Node 範例時一併加,否則 CI 會紅。Python 範例不放這個檔(守法不同,見下)。

## CI(`.github/workflows/ci.yml`)

守的是「`clone` 就能跑」這句承諾:每個 Node 範例都要 `npm ci` 裝得起來、建得出宣告的產物、且呼叫的 SDK 方法在**實際裝到的那版**上存在;每個 Python 範例都要照 README 裝得起來,並對本機的假 gateway 真的跑過一次。

範例清單由 CI **從檔案系統盤點**,以目錄裡的標記檔歸類:有 `package.json` 的是 Node 範例,有 `requirements.txt` 的是 Python 範例。新增這兩類目錄不必改 workflow。**每個頂層目錄(`scripts/`、`node_modules/` 與點開頭的除外)都必須被歸到恰好一類**:兩種標記都沒有、或兩種都有,`discover` 直接紅。所以要加第三種語言的範例,得先在 workflow 補上盤點規則與對應的 job;要加不是範例的頂層目錄,得先在 `discover` 的排除清單明講。

### Node 範例:`.ci-expect.json`

`.ci-expect.json` 是**宣告**,CI 不從程式碼反推——反推會把「東西被刪掉」誤讀成「本來就沒有」而靜靜通過:

```json
{
  "sdkMethods": ["publish", "stream", "streamWs"],
  "buildsTo": "dist/index.html"
}
```

- `sdkMethods` — 這個範例預期用到的 SDK 方法。掃不到其中任一個就紅(抓「偵測失效」與「覆蓋率縮水」);掃到的方法若不存在於 SDK 也紅(抓「SDK 改名了、範例沒跟上」)。改動範例的 SDK 用法時一併更新——但**只准增、不准減**。
- `removedSdkMethods`(選填)— `{方法: 理由}`。範例真的不再用某方法時,**別從 `sdkMethods` 刪**,而是在這裡記一筆非空理由,CI 才放行並印出理由留痕。防「照錯誤訊息更新基線」把覆蓋率靜靜降級。
- `buildsTo` — 建置後必須存在的檔案;沒有建置步驟就填 `null`。

### Python 範例:`scripts/py-run-smoke.py`

Python 範例沒有建置步驟、也沒有 lockfile,`python-example` job(Python 3.9 與 3.14)照 README 建 venv 安裝後跑 `pip check`、`py_compile`,再跑 `scripts/py-run-smoke.py`:

- **`requirements.txt` 第一行必須是 `msgmesh==X.Y.Z`**(確切版本),而且裝到的就是那一版——這一行就是 lockfile,不得改成範圍。另一行給 `httpx` 上限(SDK 自己沒給;`httpx` 1.x 的開發版會讓 0.6.0 一啟動就 `TypeError`)。升 SDK 版本時兩行一起重看。
- 腳本把範例複製到暫存目錄,對一個本機的假 gateway 實跑各種情境:正常收訊與 `Ctrl-C` / SIGTERM(結束前等手上那一則)、啟動那兩行逐字、預設值與環境變數優先、設定有問題時(key 沒填或夾帶空白、位址沒有協定、`.env` 不是 UTF-8 或讀不了)不送請求就結束、400 / 401 / 403 / 404 結束、錯誤文字裡的 key 遮成 `***`、其他錯誤持續重試且不洗版、處理函式丟例外不拖掉同批其餘訊息、stdout 被關掉時安靜結束。不需要憑證。
- **不連外是做出來的**:子行程的 `HTTP(S)_PROXY` 一律指到腳本自己開的本機攔截點(回 502 就斷線)。範例的設定讀取壞掉而落回內建的正式位址時,連線在攔截點結束,那個情境會因「試圖連外」變紅。改這支腳本時不要拿掉這一層——拿掉之後,範例一壞,冒煙就會帶著假 key 去打正式環境。這一層靠的是 SDK 用的 HTTP 函式庫會讀代理環境變數(`msgmesh` 0.6.0 成立);升 SDK 版本時先確認這一點仍然成立,再升 `requirements.txt` 的釘版。
- 本機跑法:在範例目錄用裝過 `requirements.txt` 的直譯器執行 `python ../scripts/py-run-smoke.py`。改了 `main.py` 的行為(訊息字樣、預設值、結束條件)就要一起改這支腳本的斷言與兩份 README。
- 這個 job 只在 Linux 跑;README 的指令也只寫 macOS / Linux。

背景:`chat-web` 曾因 `package.json` bump 了 SDK 版本、`package-lock.json` 沒跟著重產,`npm ci` 直接失敗**達 16 天無人察覺**——當時這個 repo 沒有 CI。

## 慣例
- commit 訊息用中文、標題+內容、不加作者資訊。
