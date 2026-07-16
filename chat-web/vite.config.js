// Vite 設定 —— 開發時(`npm run dev`)把 /api 代理到 token-broker 後端(server.js)。
// 這樣「Vite dev server(:5173)+ 另一個終端跑 node --env-file=.env server.js」就能協作:
// 前端向同源 /api/token 領 token,由代理轉到後端。正式部署則是 `npm run build` 後由 server.js
// 一併服務 dist/,不經 Vite,故此代理僅開發期生效。
import { defineConfig } from "vite";

// 代理目標埠需與 server.js 的 PORT 一致(預設 8787)。
const BROKER_PORT = process.env.PORT || 8787;

export default defineConfig({
  server: {
    proxy: {
      "/api": `http://localhost:${BROKER_PORT}`,
    },
  },
});
