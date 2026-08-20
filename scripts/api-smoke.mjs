// api-smoke —— 確認範例呼叫的 SDK 方法,在「實際裝到的那版 SDK」上真的存在。
//
// 為什麼需要它:`npm ci` 只證明裝得起來、`npm run build` 只證明打包得過,
// 兩者都不會發現「SDK 把方法改名了、範例還在呼叫舊名」——那要跑起來才炸,
// 而範例在 CI 裡不可能真的連線。這支就補這個縫。
//
// ── 設計原則:寧可誤紅,不可假綠 ──────────────────────────────────
// 靜態掃描一定掃不全(呼叫被傳進函式後改名、動態組出方法名…),所以本腳本
// **不**把「掃到幾個」當成證據,而是靠兩道獨立的閘門互相看守:
//
//   ① 該不該驗,由 package.json 宣告決定,不由掃描結果決定。
//      宣告了依賴卻一個呼叫點都掃不到 = 偵測規則失效,一律紅。
//      (早期版本反過來:掃不到就「乾淨跳過」——那等於讓失效自己判自己無罪,
//       範例改用 TypeScript 就會整條 CI 靜靜全綠而實際上根本沒驗到。)
//
//   ② 每個範例在 .ci-expect.json 的 sdkMethods 宣告它預期用到哪些方法,進版控。
//      掃到的集合必須是這份基線的超集,否則紅——於是「覆蓋率下降」本身
//      就是失敗條件,而不是一句看起來很正常的「✓ 2 個 API 皆存在」。
//
// 用法:在範例目錄底下執行 `node ../scripts/api-smoke.mjs`

import { readFile, readdir } from "node:fs/promises";
import { join, resolve, extname, relative } from "node:path";
import { pathToFileURL } from "node:url";

const dir = process.cwd();
const SDK = "@msgmesh/sdk";
const EXPECT = ".ci-expect.json";

// 慣例:範例都把 client 實例命名為 mq。改名會讓掃描歸零,再由閘門①擋下。
const INSTANCE = "mq";

// 原始碼副檔名。範例日後改用 TypeScript 或 .mjs 都要照掃 —— 漏掉副檔名
// 曾經是本腳本最嚴重的假綠來源(壞碼只要改個副檔名就全綠)。
const SRC_EXT = new Set([".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"]);

const die = (msg) => {
  console.error(`✗ ${msg}`);
  process.exit(1);
};
const rel = (p) => relative(dir, p) || ".";

/** 遞迴收集範例自己的原始碼(排開依賴與建置產物)。 */
async function sourceFiles(root) {
  const out = [];
  const skip = new Set(["node_modules", "dist", "build", ".vite", ".git"]);
  for (const ent of await readdir(root, { withFileTypes: true })) {
    if (skip.has(ent.name)) continue;
    const p = join(root, ent.name);
    if (ent.isDirectory()) out.push(...(await sourceFiles(p)));
    else if (SRC_EXT.has(extname(ent.name)) || extname(ent.name) === ".html") {
      out.push(p);
    }
  }
  return out;
}

/** Vite 專案的進入點掛在 HTML 的 <script> 上,那段也算原始碼。 */
function scriptsFromHtml(src) {
  return [...src.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)]
    .map((m) => m[1])
    .join("\n");
}

/**
 * 粗剝註解後再掃。範例的註解大量提到 API 名稱(本 repo 的風格如此),
 * 不剝就會把說明文字當成呼叫點,誤紅到完全錯的方向。
 * `[^:]` 是為了不要把 http:// 的 // 當行註解。
 */
const stripComments = (s) =>
  s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

// 只認「後面真的接呼叫括號」的寫法,並容忍換行與 ?. 與 ["…"] 存取。
// 對整份原始碼跑(不逐行),否則呼叫被換行拆開就漏掉。
// 注意 `?.` 是「取代」那個點,不是加在點前面 —— 寫成 (?:\?\.)?\. 會漏掉
// 每一個 mq?.foo() 而毫無徵兆(那個寫法只剩基線那道閘門攔得住)。
const CALL_RE = new RegExp(
  `\\b${INSTANCE}\\s*(?:` +
    `(?:\\?\\.|\\.)\\s*([A-Za-z_$][\\w$]*)` + // mq.foo(  /  mq?.foo(
    `|(?:\\?\\.)?\\s*\\[\\s*["']([^"']+)["']\\s*\\]` + // mq["foo"](  /  mq?.["foo"](
    `)\\s*\\(`,
  "g",
);

// ── 閘門①:該不該驗,由 package.json 說了算 ──────────────────────
const pkgJson = JSON.parse(await readFile(join(dir, "package.json"), "utf8"));
const declared = pkgJson.dependencies?.[SDK] ?? pkgJson.devDependencies?.[SDK];

if (!declared) {
  console.log(`· ${rel(dir)}:package.json 未宣告 ${SDK},略過 API 冒煙`);
  process.exit(0);
}

const files = await sourceFiles(dir);
const used = new Map(); // 方法名 -> 首次出現位置(報錯時指得出行號)

for (const f of files) {
  const raw = await readFile(f, "utf8");
  const src = stripComments(
    extname(f) === ".html" ? scriptsFromHtml(raw) : raw,
  );
  for (const m of src.matchAll(CALL_RE)) {
    const name = m[1] ?? m[2];
    if (!used.has(name)) {
      const line = src.slice(0, m.index).split("\n").length;
      used.set(name, `${rel(f)}:${line}`);
    }
  }
}

if (used.size === 0) {
  die(
    `${rel(dir)} 的 package.json 宣告了 ${SDK}@${declared},` +
      `卻掃不到任何 \`${INSTANCE}.<方法>()\` 呼叫。\n` +
      `  掃了 ${files.length} 個檔案。這是偵測規則失效,不是「沒用到 API」——\n` +
      `  多半是 client 實例改了名(見 scripts/api-smoke.mjs 的 INSTANCE),\n` +
      `  或用了本腳本認不得的呼叫寫法。修好偵測,別把這裡改成略過。`,
  );
}

// ── 閘門②:覆蓋率不得下降 ────────────────────────────────────────
let baseline;
try {
  baseline = JSON.parse(await readFile(join(dir, EXPECT), "utf8")).sdkMethods;
} catch {
  die(
    `${rel(dir)} 的 ${EXPECT} 缺少 sdkMethods。每個用到 ${SDK} 的範例都要宣告預期的方法基線,\n` +
      `  否則掃描漏了什麼沒人看得出來。依這次掃描結果,可直接寫入:\n\n` +
      `  "sdkMethods": ${JSON.stringify([...used.keys()].sort())}\n`,
  );
}
if (!Array.isArray(baseline)) die(`${rel(dir)}/${EXPECT} 的 sdkMethods 必須是陣列`);

const dropped = baseline.filter((m) => !used.has(m));
if (dropped.length) {
  die(
    `覆蓋率下降:${EXPECT} 的 sdkMethods 宣告了 ${dropped.join(", ")},但這次掃不到。\n` +
      `  若範例真的不再用這些方法,請一併更新 ${EXPECT};\n` +
      `  否則就是掃描規則失效了(這正是本檢查要抓的東西)。`,
  );
}

// ── 對照實際裝到的那版 SDK ────────────────────────────────────────
const sdkDir = resolve(dir, "node_modules", SDK);
const pkg = JSON.parse(await readFile(join(sdkDir, "package.json"), "utf8"));

// exports 的值可能是字串,也可能是巢狀條件物件,遞迴拆到字串為止。
const pickEntry = (e) =>
  typeof e === "string"
    ? e
    : e && typeof e === "object"
      ? pickEntry(e.import ?? e.default ?? e.node)
      : undefined;

const entry = pickEntry(pkg.exports?.["."]) ?? pkg.module ?? pkg.main;
if (typeof entry !== "string") die(`${SDK} 的 package.json 找不到可用的 ESM 進入點`);

const sdk = await import(pathToFileURL(join(sdkDir, entry)).href);
if (typeof sdk.MsgMesh !== "function") die(`${SDK}@${pkg.version} 沒有匯出 MsgMesh`);

// 只做 typeof 檢查、絕不呼叫任何方法。三個 URL 全指向死埠當保險:
// 萬一日後建構子或某個 getter 真的想連線,也打不出去。
// (選項名必須用 SDK 真正認得的這三個;寫錯會被靜默丟棄而退回 localhost 預設,
//  而這是公開 repo,錯的選項名會被讀者抄走。)
const client = new sdk.MsgMesh({
  apiKey: "smoke",
  controlPlaneUrl: "http://127.0.0.1:1",
  gatewayUrl: "http://127.0.0.1:1",
  realtimeUrl: "http://127.0.0.1:1",
});

const missing = [];
for (const [method, where] of [...used].sort()) {
  const ok = typeof client[method] === "function";
  console.log(`  ${ok ? "✓" : "✗"} ${INSTANCE}.${method}()  ${where}`);
  if (!ok) missing.push(`${method}(${where})`);
}

if (missing.length) {
  die(
    `${SDK}@${pkg.version} 沒有這些方法:${missing.join(", ")}\n` +
      `  範例落後於 SDK —— 更新範例程式碼,或把 package.json 的版本範圍釘回相容的一版。`,
  );
}

console.log(
  `✓ ${rel(dir)}:${used.size} 個 API(基線 ${baseline.length})在 ${SDK}@${pkg.version} 上皆存在`,
);
