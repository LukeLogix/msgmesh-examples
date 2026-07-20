# msgmesh-examples — MsgMesh 官方範例集

**MsgMesh**(多租戶事件總線)的官方範例／樣板集合。每個資料夾都是「`clone` 就能跑」的最小起手式,示範如何用官方 SDK [`@msgmesh/sdk`](https://www.npmjs.com/package/@msgmesh/sdk) 接入、收發即時事件。

## 現有範例
- `agent-notifier/` — Node 腳本:用 SDK `subscribe()` 訂閱 topic、收到事件就處理(給 AI agent / 後端的事件監看層)。
- `chat-web/` — 網頁聊天室(Vite),附**最小 token-broker 後端**(`server.js` 持 key、向平台鑄 5 分鐘降權 token),前端零長期 key;示範 SSE/WS 收發與多房間(room)隔離。

## 給貢獻者 / AI 助手的準則
- 每個範例維持**零內部依賴**:只用**公開 SDK 與對外介面**(SSE / HTTP / MCP),不假設任何私有服務細節。
- 範例要能只填 **gateway / realtime URL + 一把 API key** 就跑起來;**切勿**把真實金鑰、內部主機 / 網域、部署細節寫進程式碼或文件(這是公開 repo)。
- SDK 用法以 npm 上的 `@msgmesh/sdk`(及 PyPI 的 `msgmesh`)公開 API 為準;範例是**消費端**,發現 SDK 問題回報上游而非在此 fork 契約。
- 每個範例目錄自帶 `README`,新增範例時比照(說明、需要的環境變數、跑法)。

## 慣例
- commit 訊息用中文、標題+內容、不加作者資訊。
