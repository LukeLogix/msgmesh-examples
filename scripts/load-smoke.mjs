// load-smoke —— 把建好的頁面真的用瀏覽器載入一次,任何未捕捉例外就紅燈。
//
// 為什麼需要這道:2026-07-17 的 chat-web(9fa907c)在 main 上壞了**六週**——
// `start()` 在 `let mq` 之前被呼叫,暫時性死區丟 ReferenceError,頁面一載入就死在
// 「Initializing…」,network tab 連一個請求都沒有。而當時 CI 全綠,因為它只證明了
// 「裝得起來、建得出來、SDK 方法名還在」——**從來沒有把頁面載入過一次**。
// (諷刺的是這個 CI 正是為了前一次「壞了 16 天沒人發現」而建的;下一次的壞法它剛好看不到。)
//
// 不需要任何憑證:用打不通的位址建置,讓它走完整條啟動路徑。網路失敗是預期內的
// (那是**被處理過**的錯誤路徑);這裡抓的是「模組還沒跑完就炸掉」那一類。
//
// 用法:node ../scripts/load-smoke.mjs        (cwd = 範例目錄)
import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { existsSync, readFileSync, mkdtempSync, statSync } from 'node:fs';
import { extname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';

const cwd = process.cwd();
const name = cwd.split('/').pop();

// ── 沒有頁面的範例(agent-notifier 之類的純腳本)明確跳過,不是靜默通過 ──────────
const expectPath = join(cwd, '.ci-expect.json');
if (!existsSync(expectPath)) {
  console.error(`✗ ${name}:缺 .ci-expect.json`);
  process.exit(1);
}
const expect = JSON.parse(readFileSync(expectPath, 'utf8'));
if (!expect.buildsTo) {
  console.log(`· ${name}:buildsTo 為 null(無頁面產物),load-smoke 不適用 —— 明確跳過`);
  process.exit(0);
}

// ── 建置到暫存目錄。用 process env 餵 VITE_*,**不碰開發者的 .env** ──────────────
// 位址刻意用 127.0.0.1:9(discard port,必定連不上):憑證不需要,而且能證明
// 「連不上」是被處理的路徑,不是讓頁面炸掉的原因。
const out = mkdtempSync(join(tmpdir(), 'load-smoke-'));
const DEAD = 'http://127.0.0.1:9';
const build = spawnSync('npx', ['vite', 'build', '--outDir', out, '--emptyOutDir'], {
  cwd, encoding: 'utf8',
  env: { ...process.env,
    VITE_MSGMESH_GATEWAY_URL: DEAD, VITE_MSGMESH_REALTIME_URL: DEAD,
    VITE_MSGMESH_TOPIC: 'smoke.topic', VITE_MSGMESH_ROOMS: 'lobby,support' },
});
if (build.status !== 0) {
  console.error(`✗ ${name}:以冒煙設定建置失敗\n${build.stderr || build.stdout}`);
  process.exit(1);
}

// ── 零依賴靜態伺服器 ────────────────────────────────────────────────────────────
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
               '.json': 'application/json', '.svg': 'image/svg+xml', '.ico': 'image/x-icon' };
const server = createServer((req, res) => {
  const p = resolve(out, '.' + decodeURIComponent(req.url.split('?')[0]));
  // 目錄(含 `/`)一律回 index.html —— existsSync 對目錄也回 true,少了 isFile 會讀目錄而 EISDIR。
  const isFile = existsSync(p) && statSync(p).isFile();
  const f = isFile ? p : join(out, 'index.html');
  if (!p.startsWith(out) || !existsSync(f)) { res.writeHead(404).end(); return; }
  res.writeHead(200, { 'content-type': MIME[extname(f)] || 'application/octet-stream' });
  res.end(readFileSync(f));
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const url = `http://127.0.0.1:${server.address().port}/`;

// ── headless Chrome ────────────────────────────────────────────────────────────
const CANDIDATES = [
  process.env.CHROME_PATH,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome', '/usr/bin/chromium-browser', '/usr/bin/chromium',
].filter(Boolean);
const chrome = CANDIDATES.find(existsSync);
if (!chrome) {
  // 刻意 fail 而非 skip:skip 會讓「沒裝瀏覽器」看起來跟「頁面沒問題」一樣。
  console.error(`✗ 找不到 Chrome。設 CHROME_PATH,或在 CI 用 browser-actions/setup-chrome。試過:\n  ${CANDIDATES.join('\n  ')}`);
  process.exit(1);
}
const port = 9500 + (process.pid % 400);
const proc = spawn(chrome, ['--headless=new', `--remote-debugging-port=${port}`, '--no-sandbox',
  '--no-first-run', '--disable-gpu', `--user-data-dir=${out}/.chrome`, 'about:blank'], { stdio: 'ignore' });

let ver;
for (let i = 0; i < 40 && !ver; i++) {
  await new Promise(r => setTimeout(r, 250));
  try { ver = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json(); } catch {}
}
if (!ver) { console.error('✗ Chrome 起不來(DevTools 端點無回應)'); proc.kill(); process.exit(1); }

const ws = new WebSocket(ver.webSocketDebuggerUrl);
await new Promise(r => (ws.onopen = r));
let id = 0; const pend = new Map(); const errors = [];
ws.onmessage = e => {
  const m = JSON.parse(e.data);
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id); return; }
  if (m.method === 'Runtime.exceptionThrown') {
    const d = m.params.exceptionDetails;
    errors.push(d.exception?.description?.split('\n')[0] || d.text);
  }
};
const send = (method, params = {}, sessionId) => new Promise(res => {
  const i = ++id; pend.set(i, res);
  ws.send(JSON.stringify(sessionId ? { id: i, method, params, sessionId } : { id: i, method, params }));
});

const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
await send('Runtime.enable', {}, sessionId);
await send('Page.enable', {}, sessionId);
await send('Page.navigate', { url }, sessionId);
await new Promise(r => setTimeout(r, 4000));

const probe = await send('Runtime.evaluate', {
  expression: `JSON.stringify({ status: document.getElementById('status')?.textContent || '' })`,
  returnByValue: true,
}, sessionId);
const { status } = JSON.parse(probe.result.value);

ws.close(); proc.kill(); server.close();

let ok = true;
// ① 未捕捉例外 = 頁面在載入時死掉
if (errors.length) {
  console.error(`✗ ${name}:載入頁面時有未捕捉例外`);
  errors.forEach(e => console.error(`    ${e}`));
  ok = false;
}
// ② 反向確認這道檢查沒有空轉:若停在「未設定」分支,start() 根本沒跑,
//    ① 就形同虛設(綠燈只代表「什麼都沒執行」)。
if (/Not configured/i.test(status)) {
  console.error(`✗ ${name}:頁面停在「未設定」分支 —— 冒煙的 VITE_* 沒被吃到,這次檢查沒有真的執行啟動路徑`);
  console.error(`    status: ${status}`);
  ok = false;
}
if (ok) console.log(`✓ ${name}:頁面載入無未捕捉例外(status: ${status.slice(0, 70)})`);
process.exit(ok ? 0 : 1);
