# msgmesh-examples — MsgMesh 官方範例集

**MsgMesh**(多租戶事件總線)的官方範例／樣板集合。每個資料夾都是「`clone` 就能跑」的最小起手式,示範如何用官方 SDK [`@msgmesh/sdk`](https://www.npmjs.com/package/@msgmesh/sdk) 接入、收發即時事件。

## 現有範例
- `agent-notifier/` — Node 腳本:用 SDK `subscribe()` 訂閱 topic、收到事件就處理(給 AI agent / 後端的事件監看層)。
- `chat-web/` — 網頁聊天室(Vite),附**最小 token-broker 後端**(`server.js` 持 key、向平台鑄 5 分鐘降權 token),前端零長期 key;示範 SSE/WS 收發與多房間(room)隔離。

## 給貢獻者 / AI 助手的準則
- 每個範例維持**零內部依賴**:只用**公開 SDK 與對外介面**(SSE / HTTP / MCP),不假設任何私有服務細節。
- 範例要能只填 **gateway / realtime URL + 一把 API key** 就跑起來;**切勿**把真實金鑰、內部主機 / 網域、部署細節寫進程式碼或文件(這是公開 repo)。
- SDK 用法以 npm 上的 `@msgmesh/sdk`(及 PyPI 的 `msgmesh`)公開 API 為準;範例是**消費端**,發現 SDK 問題回報上游而非在此 fork 契約。
- 每個範例目錄自帶**雙語 README**:`README.md`(英文,GitHub/npm 預設門面,面向國際開發者)+ `README.zh.md`(繁中),兩份頂部互相切換連結(`**English** | [繁體中文](./README.zh.md)` ↔ `[English](./README.md) | **繁體中文**`)。**新增範例時中英兩份一起加**(勿只加單語,否則破壞雙語結構);內容含說明、需要的環境變數、跑法。

- **每個範例目錄要有 `.ci-expect.json`**(CI 讀它,見下)。新增範例時一併加,否則 CI 會紅。

## CI(`.github/workflows/ci.yml`)

守的是「`clone` 就能跑」這句承諾:每個範例都要 `npm ci` 裝得起來、建得出宣告的產物、且呼叫的 SDK 方法在**實際裝到的那版**上存在。範例清單由 CI **從檔案系統自動盤點**,新增目錄不必改 workflow。

`.ci-expect.json` 是**宣告**,CI 不從程式碼反推——反推會把「東西被刪掉」誤讀成「本來就沒有」而靜靜通過:

```json
{
  "sdkMethods": ["publish", "stream", "streamWs"],
  "buildsTo": "dist/index.html"
}
```

- `sdkMethods` — 這個範例預期用到的 SDK 方法。掃不到其中任一個就紅(抓「偵測失效」與「覆蓋率縮水」);掃到的方法若不存在於 SDK 也紅(抓「SDK 改名了、範例沒跟上」)。改動範例的 SDK 用法時一併更新。
- `buildsTo` — 建置後必須存在的檔案;沒有建置步驟就填 `null`。

背景:`chat-web` 曾因 `package.json` bump 了 SDK 版本、`package-lock.json` 沒跟著重產,`npm ci` 直接失敗**達 16 天無人察覺**——當時這個 repo 沒有 CI。

## 慣例
- commit 訊息用中文、標題+內容、不加作者資訊。
