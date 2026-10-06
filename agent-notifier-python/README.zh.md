[English](./README.md) | **繁體中文**

# agent-notifier-python —— MsgMesh 事件監看腳本(Python)

[`agent-notifier`](../agent-notifier) 的 Python 版:訂閱一個 topic,收到事件就處理,讓你把事件流餵給 agent / 後端邏輯。正常路徑與 Node 版相同(同樣四個設定、同樣格式的兩行啟動訊息(前綴是各自的名字)、同一條發測試事件的指令);兩者不同的地方列在下面「與 Node 版的差別」。

- **收**:PyPI 上 [`msgmesh`](https://pypi.org/project/msgmesh/) SDK 的 `subscribe()` —— 長輪詢迴圈,`GET {gateway}/v1/topics/{topic}/messages`,收到就呼叫你的 handler,回傳一個停止迴圈的函式。
- SDK 是同步 API:輪詢迴圈跑在背景執行緒,不需 WebSocket;暫時性錯誤 SDK 會自己等一下再重試。

## poll/consume 是 firehose —— 房間(room)在這裡用不了

`subscribe()`(以及底層的 poll / consume)吃的是**整個 topic** 的 firehose:所有房間的每一則訊息,每則由 group 中一個 consumer 處理(分攤消費;投遞語義是 **at-most-once**——取到一批時位移即前進,回應途中遺失的訊息不會補送。需要硬性 at-least-once 處理請改用 webhook 或 SSE/WS)。它**不做房間(room)過濾**,而且 **room-scoped 憑證(token 的 `rooms` 非空)呼叫 poll/consume 會被回 403**。這支範例要用**不限房間**的 key(consumer/subscribe 能力、`rooms` 空 = 全房間)。

poll 為什麼不能依房間過濾、只想收某個房間的事件該用什麼,寫在 [`agent-notifier` README](../agent-notifier/README.zh.md) 的同名小節,在這裡完全適用。要自己依房間分流,在 `handle_event` 裡讀 `msg.room`。

## 跑起來

需要 Python ≥ 3.9(用 `python3 --version` 確認),以及帳號、API key 與 `orders` 這個 topic:見根 README「共同前置」。這份 README 的指令是照 macOS 與 Linux 寫的,沒有在 Windows 上試過。

```bash
cp .env.example .env
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

打開 `.env` 填入 `MSGMESH_API_KEY`。在自己電腦上試跑,可以直接填一鍵開箱給的 starter key(見根 README「共同前置」)。`.env.example` 已把 `MSGMESH_GATEWAY_URL` 設成 `https://msgmesh-api.alderflux.com`,維持原值即可。接著啟動:

```bash
.venv/bin/python main.py
```

`main.py` 會自己讀旁邊的 `.env`:一行一個 `KEY=VALUE`。值一直到行尾為止;只會去掉前後的空白、一對外層引號,以及行首的 `export`。所以行尾不要加註解:註解會變成值的一部分。shell 裡已經設定的變數優先於這個檔。

啟動後會印出下面兩行,接著每收到一則事件就印出來:

```
agent-notifier-python: subscribing to topic "orders" (group=agent-notifier-python)... press Ctrl-C to quit
agent-notifier-python: if this group has not read this topic before, it starts from the oldest message still within the topic's retention, so messages already in the topic arrive first
```

要看到效果,在這個資料夾另開一個終端:下面第一行把 `.env` 裡的每個變數都匯出到這個 shell(四個都是,不只 `MSGMESH_API_KEY`),第二行往 `orders` 發一筆。之後若在同一個終端啟動 `main.py`,這些匯出的值會優先於你後來對 `.env` 做的修改。

```bash
export $(grep -v '^#' .env | xargs)
curl -X POST https://msgmesh-api.alderflux.com/v1/topics/orders/messages -H "Authorization: Bearer $MSGMESH_API_KEY" -H "Content-Type: application/json" -d '{"item":"test-order"}'
```

回應是 `{"partition":…,"offset":…}`,第一個終端會出現像下面這樣的一行(時間、partition、offset 以你的為準):

```
[2026-10-06T03:11:26.189Z] orders#0/0 {"item": "test-order"}
```

`Ctrl-C` 停止腳本,結束碼是 0。

**一直沒有事件時。** 預設情況下,topic 不存在(或 `MSGMESH_TOPIC` 的名稱打錯)時,收的這一邊不會報錯:腳本印出啟動那兩行之後就一直沒有事件,和 topic 裡還沒有事件時一樣。用上面那條 `curl` 分辨:topic 還沒建的話,它得到的是錯誤(HTTP 404,topic not found),而不是 `{"partition":…,"offset":…}`。

第二行講的是 group 第一次讀這個 topic 的情況(保留期多長由方案決定)。把 `MSGMESH_TOPIC` 指到已經有訊息的 topic(例如用過 `chat-web` 之後的 `chat.lobby`)、或換一個 `MSGMESH_GROUP`,啟動後會先收到既有的訊息,每次投遞照常再計一次 operations(訊息每 16 KiB 算 1 個 operation,發布時算一次、每次投遞再算一次)。同一個 group 重啟則從上次的位置接續;閒置很久的 group 會重新從保留期內最舊的訊息開始。這裡的預設 group 與 Node 版不同,所以先跑過 `agent-notifier` 並發過測試事件的人,第一次啟動這支腳本時也會收到那些事件。

### 啟動後馬上結束時

下表這幾種情況,腳本會印出原因並以結束碼 1 結束:

| 訊息裡有這段字 | 意思 | 怎麼處理 |
| --- | --- | --- |
| `Missing MSGMESH_API_KEY` | `main.py` 旁邊沒有 `.env`,或裡面的 key 是空的、仍是 `replace-me` | 在 `.env` 填入 `MSGMESH_API_KEY` |
| `MSGMESH_API_KEY contains a character that is not plain ASCII` | 複製時帶到了 key 以外的字元 | 重新複製一次 key |
| `MSGMESH_API_KEY contains whitespace or a control character` | key 夾帶了空白、tab 或換行 | 重新複製一次 key |
| `MSGMESH_GATEWAY_URL must start with https:// or http://` | 位址少了開頭的協定 | 用 `https://msgmesh-api.alderflux.com` |
| `.env is not UTF-8 text` | 檔案存成了別的編碼(例如 UTF-16) | 把 `.env` 存成 UTF-8 |
| `.env could not be read` | 檔案在,但你的使用者沒有讀取權限 | 修正 `.env` 的權限 |
| `rejected the request for topic "orders" as invalid (HTTP 400)` | 平台不接受這個請求。多半是 topic 名稱不合規則,例如 `.env` 的值後面加了註解 | 檢查 `MSGMESH_TOPIC` |
| `the API key was rejected (HTTP 401)` | key 不對,或已被刪除 | 檢查 `MSGMESH_API_KEY`,必要時重簽一把 |
| `refused to let this key read topic "orders" (HTTP 403)` | 多半是這把 key 在這個 topic 上沒有 consumer 或 subscribe 能力(只能發布的 key 收不了),或限定了房間 | 換一把能收的 key:見根 README「共同前置」第 2 項 |
| `topic "orders" was not found (HTTP 404)` | 只有兩種情況會出現:帳號在面板 Keys 頁開了「要求 topic 先建立(strict topics)」而這個 topic 還沒建,或 `MSGMESH_GATEWAY_URL` 指到了 MsgMesh 以外的服務。這個開關關著時(預設),topic 不存在不會報錯:見上面「一直沒有事件時」 | 在面板建立這個 topic,或把 `MSGMESH_TOPIC` 改成已存在的;檢查訊息裡印出的位址 |

帶 HTTP 狀態碼的那四種,訊息的下一行是伺服器回的原因。如果用到的 key 來自環境變數、而且與 `.env` 裡的不同,會再多印一行說明。舉例:在跑過上面那行 `export` 的終端啟動 `main.py`,而 `.env` 在那之後改過,就會是這種情況。錯誤文字裡若出現 key 本身,會印成 `***`。

其他錯誤(網路問題、5xx 回應、限流)不會讓腳本結束:SDK 會持續重試。腳本會印一行以 `agent-notifier-python: subscribe error` 開頭的訊息,帶例外類別與 gateway 位址。同一種錯誤持續發生時,這一行每 30 秒最多印一次:第一行不附次數,第二次起附上這種錯誤到目前為止的累計次數。

讀這支腳本輸出的那一端不見了的話(例如 `.venv/bin/python main.py | head -1`),腳本不再印任何東西,以結束碼 1 結束。

### 與 Node 版的差別

- **預設 group。** 是 `agent-notifier-python`,不是 `agent-notifier`。同一個 group 的多個實例會分攤訊息;兩個範例若用同一個名字又同時開著,每則事件只會出現在其中一邊。
- **HTTP 400 / 401 / 403 / 404。** 401 兩邊都會結束:Node 版印一行後以結束碼 0 結束;這一版印出原因並以結束碼 1 結束(Python SDK 遇到 401 會永久停止輪詢,腳本不結束的話就只是掛在那裡什麼都不做)。key 讀不了這個 topic(403)時,Node 版每秒印一行錯誤並持續重試;這一版印出原因後結束。400 與 404(topic 不存在時,只有開了嚴格 topic 的帳號會拿到 404)在兩邊都和 403 一樣。403 不一定是永久的,長時間執行的 worker 若想繼續重試,把 `main.py` 裡 `report` 的 403 那一段改成只印訊息、不呼叫 `give_up`。
- **key 仍是 `replace-me` 視同沒填**,而且 key 與位址會在送出任何請求之前先檢查。Node 版只檢查 key 不是空的。
- **`MSGMESH_GATEWAY_URL` 有預設值。** 完全沒設這個變數時,`main.py` 用 `https://msgmesh-api.alderflux.com`。
- **`.env` 由 `main.py` 自己讀**,不是由執行環境讀(`node --env-file`)。
- **事件印成 JSON 文字**(`{"item": "test-order"}`);Node 版印的是解析後的物件(`{ item: 'test-order' }`)。

## 設定

| 變數 | 用途 |
| --- | --- |
| `MSGMESH_GATEWAY_URL` | 收發服務位址:`https://msgmesh-api.alderflux.com`(`.env.example` 已填好;沒設這個變數時 `main.py` 用的也是它) |
| `MSGMESH_API_KEY` | API key(需 consumer / subscribe 能力,且**不限房間**——poll 吃整個 topic,room-scoped token 會被 403) |
| `MSGMESH_TOPIC` | 要監看的 topic,預設 `orders`,面板一鍵開箱預設已建立。既有帳號或當時沒勾選的人,才需要自己先建(見根 README「共同前置」) |
| `MSGMESH_GROUP` | 消費者 group,預設 `agent-notifier-python`(同 group 多實例分攤訊息)。新的 group 從保留期內最舊的訊息開始收 |

## 改成你的用途

編輯 `main.py` 裡的 `handle_event(msg)`:`msg.value` 是原始字串(範例會試著 `json.loads`),`msg.partition` 與 `msg.offset` 是這則訊息在 topic 裡的位置。把 `say(...)` 那一行換成寫入 DB、呼叫下游 API、或交給 LLM/agent 決策即可。若你的訊息有帶房間(發佈時的 `room`),`msg.room` 就是房間名(沒帶時是 `None`),可據以 per-room 分流(poll 收的是全房間 firehose,分流由你在這裡做)。

handler 在 SDK 的背景執行緒上一則一則執行,所以處理得慢會延後下一次輪詢。SDK 是同步 API;在 async 框架裡需自行包 executor。

`handle_event` 丟出例外時,腳本會印出 traceback,然後繼續處理下一則。這靠的是 `on_message` 裡的那個 `try`:沒有它的話,SDK(0.6.0)會把例外交給 `on_error`,並跳過已經取回的這一批裡剩下的訊息,而那些訊息不會再送一次。不管哪一種,處理失敗的那一則都不會重試。

## 檔案

- `main.py` —— 讀 `.env`、檢查設定、`subscribe()` 監看、處理事件、收到 `Ctrl-C` 或 SIGTERM 時停止。
- `requirements.txt` —— SDK 釘在確切版本(這裡沒有 lockfile,裝到哪一版 SDK 由這一行決定),另外給 SDK 用的 HTTP client `httpx` 一個版本上限。
- `.env.example` —— 設定範本(複製成 `.env`)。
