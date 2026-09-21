# qs-dash — 全球多资产实时终端（Dynamic Finance Dashboard）：规格与验收标准

版本 v1.1（数据源、字段映射、跨源一致性均已本机实测；实现完成并自测通过：`check` 6/6、`pytest` 32/32、`smoke_e2e` 27/27） · 目标环境：macOS / Python 3.9.6（`/usr/bin/python3`）
依赖：**标准库 only**（`urllib` `http.server` `json` `threading` `xml.etree`）——不新增依赖，不引入 pandas

本文件与 `../BC/SPEC.md`（加密）、`../Stock/SPEC-STOCK.md`（A 股）**互不相关**：独立目录、独立进程、独立缓存。

---

## 1. 目标与边界

**目标**：一个覆盖 **5 类资产**（Equities / FX / Commodities / Bonds / Crypto）+ **实时新闻** 的单进程终端：
浏览器打开即连续刷新，每个报价都带**来源、端点、抓取时间**，任一源挂掉**显式报错**而不是留一个看起来正确的数字。

**做法**：标准库自建端点适配层直取第三方 JSON / XML / RSS（沿用 BC 与 Stock 的架构哲学）。

**明确不做（v1）**
- 不做下单、不接券商、不碰资金账户；不存任何 API key（全部为公开免鉴权端点）
- 不做 K 线图、不做技术指标、不做回测（那是 BC / Stock 的领域）
- 不做 tick 级 WebSocket；v1 是**轮询聚合**，按资产类别分档刷新
- 不做用户系统、不做持久化历史（v1 只保留进程内「最后已知有效值」）

**不做假的铁律（贯穿实现）**
1. 端点失败 → 该面板显示 `FEED DOWN` + 错误原文 + 最后有效值的**年龄**，不显示 0、不插值、不外推
2. 无法实证的字段一律不展示（宁可空列），导出的字段必须能指到本规格 §2 的实测行
3. 每个报价携带 `source / endpoint / fetched_at / latency_ms`，UI 底部可查

---

## 2. 数据可行性（2026-09-21 本机实测，非推断）

实测脚本：`probe_sources.py`（51 个端点）、`dump_fields.py`（字段序位）、`verify_mapping.py` / `verify_mapping2.py`（映射求解 + 跨源核对）。
原始结果落盘 `data/probe_results.json`。

### 2.1 端点存活（51 个候选中 40 个可用）

| 类别 | 可用 | 不可用（已证伪） |
|---|---|---|
| Equities | **5/10** sina `gb_*`、sina `int_*`、sina `sh/sz`、tencent `us*`、nasdaq api | yahoo `v8/chart` **HTTP 429**、yahoo `v7/quote` **429**、stooq **404**、fmp demo **401** |
| FX | **5/6** sina `fx_*`、frankfurter、open.er-api、ECB XML | yahoo FX **429** |
| Commodities | **5/7** sina `hf_*`、sina `nf_*`、tencent `hf_*` | yahoo `GC=F` **429**、stooq `gc.f` **404** |
| Bonds | **3/6** US Treasury XML（名义 + 实际）、treasury fiscaldata API | FRED CSV **超时**、yahoo `^TNX` **429** |
| Crypto | **7/7** binance、coinbase、coingecko、kraken、okx、bybit | — |
| News | **15/16** CNBC×2、MarketWatch、Yahoo、Investing×2、CoinTelegraph、TheBlock、Decrypt、FT、BBC、GoogleNews×2、SeekingAlpha、ZeroHedge | coindesk **HTTP 308** |

> **Yahoo Finance 全线 429 是本机硬事实**，因此 `yfinance`（GitHub 最流行的行情库）在本机**不可用**，
> 与 `akshare`（依赖东方财富，见 SPEC-STOCK §2）同属「流行但本机不通」。这不是取舍，是实测否决。

### 2.2 字段映射（实证，非记忆）

字段序位不靠文档、不靠记忆，靠两类可复现判据解出来：

**(a) Sina 美股 `gb_*`** — 判据 `([1]-[26])/[26]*100 == [2]`，5 个标的全部命中：

| 标的 | last [1] | prev_close [26] | 算得 | 端点 [2] | 一致 |
|---|---|---|---|---|---|
| gb_aapl | 336.13 | 337.00 | −0.2582% | −0.26% | ✓ |
| gb_msft | 493.78 | 497.75 | −0.7976% | −0.80% | ✓ |
| gb_nvda | 222.27 | 219.34 | +1.3358% | +1.34% | ✓ |
| gb_tsla | 364.27 | 366.20 | −0.5270% | −0.53% | ✓ |
| gb_amzn | 253.71 | 251.19 | +1.0032% | +1.00% | ✓ |

→ `[0]名称 [1]最新 [2]涨跌幅 [3]行情时间 [4]涨跌额 [5]开盘 [6]最高 [7]最低 [8]52w高 [9]52w低 [10]成交量 [12]市值 [14]市盈率 [26]昨收`

**(b) Sina 全球指数 `int_*`** — 只有 4 字段，判据 `[2] == [1]*[3]/100`，6/6 命中：`[0]名称 [1]最新 [2]涨跌额 [3]涨跌幅`

**(c) Sina 国际期货 `hf_*`** — 与腾讯 `hf_*` **独立源逐标的比对**，8/8 命中（涨跌幅误差 < 0.05pp）：

| 品种 | sina [0] | sina [7]昨结 | 算得% | tencent [1]% | 一致 |
|---|---|---|---|---|---|
| hf_GC 纽约黄金 | 4407.74 | 4424.90 | −0.388 | −0.39 | ✓ |
| hf_CL 纽约原油 | 93.913 | 96.080 | −2.255 | −2.26 | ✓ |
| hf_SI 纽约白银 | 66.951 | 67.149 | −0.295 | −0.32 | ✓ |
| hf_HG 美铜 | 673.344 | 669.150 | +0.627 | +0.63 | ✓ |
| hf_NG 美国天然气 | 3.010 | 3.043 | −1.084 | −1.08 | ✓ |
| hf_C 美国玉米 | 528.81 | 526.00 | +0.534 | +0.53 | ✓ |
| hf_S 美国大豆 | 1311.95 | 1303.50 | +0.648 | +0.62 | ✓ |
| hf_W 美国小麦 | 757.25 | 752.25 | +0.665 | +0.66 | ✓ |

→ `[0]最新 [2]买价 [3]卖价 [4]最高 [5]最低 [6]时间 [7]昨结 [8]开盘 [12]日期 [13]名称`

**(d) Sina 外汇 `fx_*`** — **单次载荷解不出**（8 个货币对里 5 个无解），改用**双次采样差分**定位实时字段（间隔 25 秒）：

- 变动字段：`[0]时间 [1] [2] [8] [10]涨跌幅 [11]涨跌额`；静止字段：`[3] [4] [5] [6] [7] [9]名称 [12] [14]52w高 [15]52w低`

由此解出 **`[8]=最新价`、`[3]=昨收`**，回代校验**精确命中**：

| 货币对 | [8]最新 | [3]昨收 | ([8]−[3])/[3]×100 | 端点 [10] | 涨跌额 [11] |
|---|---|---|---|---|---|
| fx_susdcny | 6.6956 | 6.6984 | **−0.0418%** | −0.0418% ✓ | −0.0028 ✓ |
| fx_seurusd | 1.1482 | 1.1483 | −0.0087% | −0.01% ✓ | −0.0001 ✓ |
| fx_susdjpy | 156.79 | 156.86 | −0.0446% | −0.04% ✓ | −0.07 ✓ |
| fx_sgbpusd | 1.3384 | 1.3393 | −0.0672% | −0.07% ✓ | −0.0009 ✓ |

→ **只取 `[8] [3] [10] [11] [0] [9] [17]`**；`[5] [6]` 疑似买卖价但 USDCNY 上点差达 170bp 且与最新价不自洽 → **不展示**（§6 已知局限）。

**(e) 美债 XML** — 去命名空间解析 `entry/m:properties/d:BC_*`，2026 年 **180 条**，最新 `2026-09-18`：
1M 3.97 / 3M 4.14 / 6M 4.24 / 1Y 4.44 / 2Y 4.76 / 3Y 4.83 / 5Y 4.86 / 7Y 4.93 / 10Y 5.01 / 20Y 5.38 / 30Y 5.34
派生：**10Y−2Y = +0.250**，**10Y−3M = +0.870**。实际收益率曲线同结构可用。

**(f) 加密跨源一致性** — 六源同刻取 BTC 现货，极差 **66.08 美元 = 0.0813%**（阈值 0.3%）：
binance 81350.08 / coinbase 81322.58 / kraken 81323.70 / coingecko 81284.00 / okx 81330.40 / bybit 81334.50 → 互证成立，**主源 binance**（唯一同时给 24h 涨跌幅+高低+量）。

**(g) 新闻 RSS** — 8 个 feed 的 `title/link/pubDate` **字段完整率 100%**（条目级）：

| feed | 条数 | title | link | pubDate | source |
|---|---|---|---|---|---|
| CNBC Top | 30 | 30 | 30 | 30 | 0 |
| CNBC Markets | 30 | 30 | 30 | 30 | 0 |
| MarketWatch | 10 | 10 | 10 | 10 | 0 |
| Yahoo Finance | 49 | 49 | 49 | 49 | 49 |
| Investing | 10 | 10 | 10 | 10 | 0 |
| CoinTelegraph | 30 | 30 | 30 | 30 | 0 |
| FT | 11 | 11 | 11 | 11 | 0 |
| BBC Business | 54 | 54 | 54 | 54 | 0 |
| Google News | 100 | 100 | 100 | 100 | 100 |

→ `source` 缺失时回填 feed 自身的 `channel/title`，不置空。

**(g-2) `pubDate` 三种格式并存（实现期实测发现）** — 只认 RFC822 会**静默丢掉约 13%** 的条目：

| 格式 | 样例 | 来源 | 实测条数 |
|---|---|---|---|
| RFC822 | `Mon, 21 Sep 2026 10:00:00 GMT` | 多数 feed | 449 |
| ISO8601 | `2026-09-19T23:02:22Z` | Yahoo Finance | 49 |
| 无时区裸时间 | `2026-09-21 02:13:49` | Investing.com | 19 |

→ 三种都必须解析。裸时间**不含时区信息，不猜它是哪个时区**：按 UTC 解析并置 `tz_assumed=True`，
UI 以 `~` 前缀标注，使「假定时间」与「端点明确给出的时间」可区分（§6.9）。实测 **517/517 全部解析成功**。

### 2.3 已证伪但不能用的
`sina nf_*`（上期所/INE）字段可读（`[2]开盘 [3]高 [4]低 [8]最新`），但 **`[10]` 是否为「昨结算」未获独立源证实**
（nf_SC0 昨结 754.4 vs 最新 704.1 意味着 −6.7%，无法证伪也无法证实）→ **v1 不纳入**，列入 §6 未决。
`int_dax` 返回字段数 < 4，解析即崩 → 剔除。

---

## 3. 选型结论（GitHub 星数为证据）

`probe_github.py` / `probe_github_topics.py` 经 `api.github.com` 实测（2026-09-21）：

| 仓库 | 星数 | Fork | 最近推送 | 许可证 | 结论 |
|---|---|---|---|---|---|
| OpenBB-finance/OpenBB | 73,312 | 7,587 | 2026-09-19 | NOASSERTION | **仅作 UI/信息架构参考**；依赖树过大 |
| ccxt/ccxt | **44,078** | 8,848 | 2026-09-20 | MIT | 加密最流行；本机已装，但 v1 直取 REST 即可 |
| microsoft/qlib | 48,694 | 7,709 | 2026-09-17 | MIT | 研究框架，非行情源 → 不用 |
| ranaroussi/yfinance | 25,301 | 3,422 | 2026-09-17 | Apache-2.0 | 最流行行情库，但 **Yahoo 本机 429** → 不可用 |
| akfamily/akshare | 22,662 | 3,515 | 2026-09-20 | MIT | 依赖东方财富，本机半残 → 不可用 |
| QuantConnect/Lean | 21,706 | 5,253 | 2026-09-18 | Apache-2.0 | 引擎，非数据源 → 不用 |
| plotly/plotly.js | 18,338 | 2,034 | 2026-09-17 | MIT | 图表库，v1 不做图 → 不用 |
| tradingview/lightweight-charts | 17,317 | 2,605 | 2026-09-18 | Apache-2.0 | 同上 → 不用 |
| codelucas/newspaper | 15,161 | 2,116 | 2026-09-15 | MIT | 正文抽取，v1 只要标题 → 不用 |
| adbar/trafilatura | 6,843 | 431 | 2026-09-11 | Apache-2.0 | 同上 → 不用 |
| pydata/pandas-datareader | 3,269 | 693 | 2026-07-21 | NOASSERTION | 后端多为已 429 的源 → 不用 |
| kurtmckee/feedparser | 2,424 | 378 | 2026-09-07 | NOASSERTION | RSS 标准库 `xml.etree` 30 行可替代 → 不用 |

**结论**：流行度证据指向的库在本机**要么不通（yfinance/akshare）要么收益低于成本（feedparser/plotly）**，
因此沿用 BC/Stock 哲学——**标准库直取 + 自建适配层**，把依赖风险换成自己维护的端点适配层。
UI 参考 Bloomberg 终端的**信息密度与配色语义**（非复制任何实现）。

---

## 4. 验收标准（逐条可证伪）

### AC-D1 网络层 `qsdash/net.py`
- **AC-D1.1** `fetch(url, headers, encoding, timeout, retries)` 返回 `{ok, status, body, bytes, latency_ms, fetched_at, endpoint, error}`；**失败不抛异常到调用方**，以 `ok=False` + `error` 表达。
- **AC-D1.2** 编码必须显式指定；sina/tencent 为 **GBK**，其余 UTF-8。解码用 `errors="replace"` 且失败不算成功。
- **AC-D1.3** 重试仅针对网络层异常（超时/断连），**不重试 HTTP 4xx/5xx**（4xx 是端点否决，重试是噪音）。
- **AC-D1.4** 每次抓取记录 `fetched_at`（本地时区 ISO8601）+ `latency_ms`，随报价一并上行到 UI。

### AC-D2 行情适配 `qsdash/markets.py`
- **AC-D2.1** 五个适配器 `equities/fx/commodities/bonds/crypto` 各自返回统一结构 `Quote`，字段：`symbol,name,last,prev_close,change,change_pct,open,high,low,volume,currency,source,endpoint,fetched_at,latency_ms,quote_time,extra`。
- **AC-D2.2** 字段序位必须与 §2.2 实证表**逐位一致**；不得出现未在 §2.2 列出的索引。
- **AC-D2.3** 无法解析的标的进入 `skipped: [{symbol, reason}]` 并在 UI 可见；**不得静默丢弃**。
- **AC-D2.4** `change_pct` 优先取端点原值；无原值时由 `(last-prev_close)/prev_close*100` 计算，且两者不一致超过 **0.02pp** 时以计算值为准并在 `extra.pct_conflict=True` 标记。
- **AC-D2.5** FX 只输出 §2.2(d) 的 7 个已验证索引；买卖价字段不输出。
- **AC-D2.6** Commodities 只用 `hf_*`（国际盘），不含 `nf_*`（§2.3 未决）。
- **AC-D2.7** Bonds 输出整条曲线 + 两个利差（10Y−2Y、10Y−3M），并标注 `as_of`（美债数据的自然日，可能滞后于当前交易日）。

### AC-D3 新闻适配 `qsdash/news.py`
- **AC-D3.1** 15 个 RSS feed 并发抓取，单 feed 超时不影响其他 feed。
- **AC-D3.2** 解析 `channel/item` 的 `title/link/pubDate/description`；`source` 缺失时回填 feed 标题（实测 GoogleNews/Yahoo 有 `source`，其余无）。
- **AC-D3.3** 去重键 = `link`（无 link 时用 `title`）；同一条新闻在多 feed 出现只保留一次，并累计 `feeds` 列表。
- **AC-D3.4** `pubDate` 必须覆盖 RFC822 / ISO8601 / 无时区裸时间三种格式（§2.2 g-2）；**只有真解析不出**才 `ts=None` 并显示 `—`，**不得用当前时间冒充发布时间**；无时区的时间按 UTC 解析并置 `tz_assumed=True`，UI 以 `~` 标注，不得静默当成本地时间。
- **AC-D3.5** 输出按时间倒序；无时间戳的排在末尾。

### AC-D4 聚合与新鲜度 `qsdash/hub.py`
- **AC-D4.1** 每个资产类别独立刷新周期：crypto **5s**、equities/fx **10s**、commodities **15s**、bonds **900s**、news **90s**。
- **AC-D4.2** 保留「最后已知有效值」；源失败时 `Snapshot.ok=False` 且带 `error`，同时给出 `last_good_age_s`。
- **AC-D4.3** UI 侧：`ok=True` 正常着色；`ok=False` 面板置灰 + 顶部 `FEED DOWN` 条 + 显示错误原文。**绝不把 stale 值渲染成实时值**。
- **AC-D4.4** `snapshot()` 线程安全（锁保护）；任何适配器抛异常被捕获并转成 `ok=False`，不拖垮其他类别。

### AC-D5 服务端 `qsdash/server.py`
- **AC-D5.1** 标准库 `ThreadingHTTPServer`，绑定 `127.0.0.1`（默认端口 8848），**默认不对外网卡监听**。
- **AC-D5.2** 路由：`GET /` 静态页；`GET /api/snapshot` 全量 JSON；`GET /api/stream` SSE 推送；`GET /api/health`。
- **AC-D5.3** SSE 在快照变化时推送，并每 **1s** 推送心跳（含服务端时钟），客户端断开不报错。
- **AC-D5.4** 静态文件路径做**目录穿越防护**（拒绝 `..`）。
- **AC-D5.5** 无第三方 WSGI/ASGI 框架。

### AC-D6 界面（Bloomberg 风格）
- **AC-D6.1** 暗底 + 琥珀/绿/红语义色；等宽字体；信息高密度；顶部功能键栏 **F1 总览 / F2 股票 / F3 外汇 / F4 商品 / F5 债券 / F6 加密 / F7 新闻**。
- **AC-D6.2** 顶部跑马灯 ticker tape 连续滚动全部标的。
- **AC-D6.3** 价格上涨闪绿、下跌闪红，**仅在值实际变化时**闪（不做无意义动画）。
- **AC-D6.4** 每面板页脚常驻 `SRC / 端点 / 延迟 / 抓取时间`（AC-D1.4 的可见化）。
- **AC-D6.5** 键盘 `F1..F7` 切页、`ESC` 回总览；鼠标可点亦可。
- **AC-D6.6** 无任何外部 CDN/字体/图片请求（离线可渲染，字体用系统等宽栈）。

### AC-D7 命令行 `qsdash/__main__.py`
- **AC-D7.1** `python3 -m qsdash serve [--port] [--host]` 起服务。
- **AC-D7.2** `python3 -m qsdash check` **一次性**打全部源，控制台输出每类资产 `ok/失败/标的数/延迟`，非零退出码表示有源失败（供自测与 CI）。
- **AC-D7.3** `python3 -m qsdash snapshot --json` 打印一次全量快照，便于对账。
- **AC-D7.4** 不依赖 `pytest` 即可运行（pytest 仅用于测试）。

### AC-D8 国际化与新闻翻译（EN ⇄ ZH）

设计前提（实测，见 §9）：可用翻译端点只有 MyMemory，匿名额度 **5000 字符/日**，
而新闻 517 条 ≈ 31,000 字符 ≫ 额度。因此**「翻译全部新闻」在物理上不可能**，
架构必须是「按需 + 双层缓存 + 额度护栏」，而不是批量预翻。

- **AC-D8.1** 界面语言支持 `en` / `zh` 两种，切换**不刷新页面**；选择持久化（`localStorage`），并可由 URL 指定（`#zh`）。
- **AC-D8.2** 界面文案随语言切换：功能键、列头、面板标题、状态栏、空态与错误文案。**行情代码与标的名称不翻译**（AAPL、纽约黄金 等保持端点原值）。
- **AC-D8.3** 新闻翻译**按需触发**：只翻译当前展示的条目（默认当前视窗，上限可配），**绝不批量预翻全部条目**。
- **AC-D8.4** 翻译经服务端 `POST /api/translate` 代理，浏览器**不直连第三方**（避免 CORS，也避免把额度消耗点散到客户端）。
- **AC-D8.5** 翻译缓存双层：服务端持久化 `data/translation_cache.json`（**重启不重复消耗额度**）+ 浏览器内存缓存；命中缓存的条目**不得再次发起网络请求**。
- **AC-D8.6** 额度护栏：记录当日已用字符数；将超限或 `quotaFinished=true` 时**停止请求**，返回 `ok=false` + 原因，UI 显示原文并标注「未翻译」。**绝不返回编造的译文或空字符串**。
- **AC-D8.7** 译文可见性：翻译条目带 `MT` 标记与 provider 来源；可一键切回原文。
- **AC-D8.8** 双向：`to` 支持 `en` / `zh`；源语言用 `Autodetect`，不要求调用方判断源语言。
- **AC-D8.9** 翻译失败/超时**不影响新闻本身**：标题、链接、时间照常显示（翻译是叠加层，不是依赖）。
- **AC-D8.10** 翻译服务不可用时，**界面文案切换仍可用**（i18n 与翻译两者解耦）。

---

## 5. 自测（交付前必跑）

实测结果（2026-09-21，本机）：**全部通过**。

| # | 命令 | 覆盖 | 结果 |
|---|---|---|---|
| 1 | `python3 -m qsdash check` | 六类全链路体检 | **6/6 ok，退出码 0** |
| 2 | `python3 -m pytest` | 55 项离线单测，不打外网 | **55 passed** |
| 3 | `python3 smoke_e2e.py` | 44 项端到端：真起服务、真打接口、真读 SSE | **44/44 passed** |
| 4 | `node smoke_client.js` | 40 项客户端自测：jsdom 真跑 terminal.js，含翻译失败路径 | **40/40 passed** |

`smoke_e2e.py` 断言的具体内容：静态页与三个静态资源 200；目录穿越（`..`、`..%2f`、跨项目路径）全部 404；
快照含全部 6 类且 `classes_ok=6`；每类都有 `source / fetched_at / latency_ms`；
**64 个报价全部满足 `(last-prev)/prev == change_pct`（±0.03pp）**；无伪造 0 值；
新闻 517 条 title/link/pubDate 全解析、按时间倒序、15/15 feed 成功；
SSE 返回 `text/event-stream` 且 15s 内至少收到 2 个事件、事件类型合法。

离线单测把 `net.fetch` 换成返回 `tests/fixtures/` 真实样本的假实现，因此可以**逐位锁定字段索引**
（§2.2 的每一条实证判据都有对应测试守着）——这是本项目最容易被「凭记忆改坏」的地方。

### 5.1 实现期被验证抓出的真实缺陷（已修复）

| 缺陷 | 现象 | 根因 | 修复 |
|---|---|---|---|
| 加密全线 0 条 | binance `ticker/24hr` **HTTP 400** | `json.dumps` 默认分隔符为 `", "`，URL 编码后带 `%20`，binance 拒绝；紧凑编码即正常 | `separators=(",", ":")` |
| 新闻 68 条无时间 | 13% 条目 `ts=None` | 解析器只认 RFC822；Yahoo 用 ISO8601、Investing 用无时区裸时间 | 三格式依次尝试，裸时间置 `tz_assumed` |
| 6 个商品代码为空 | `hf_PL/PA/RB/ZC/ZS/SB` 字段缺失 | sina 不提供这些代码 | 标的池按实测收敛到 12 个 |

### 5.2 未能验证的一项（如实记录，不当作已完成）

**像素级截图仍未取得**。本机仅装有 Edge，其 headless 模式**硬编码**写入
`~/Library/Application Support/Microsoft Edge/`（`SingletonLock`、`Crashpad`），被文件沙箱拒绝（SIGTRAP）；
未为一张截图申请放宽沙箱权限。

因此 **AC-D6 的「视觉呈现」仍未经像素确认**——配色、间距、对齐是否好看，没有被机器验证过。

但「页面能不能跑」已不再是盲区：`smoke_client.js` 用本机 DSH checkout 里已有的 **jsdom**
真正执行 `terminal.js`（加载真 `index.html`、喂真实快照 fixture、点击语言按钮与 MT 标记），
**40/40 通过**。它覆盖的是 DOM 行为与状态机，不是像素：

- 启动无 JS 异常；功能键 7 个；`en` 下文案为英文，`zh` 下切为中文，`<html lang>` 与 hash 同步
- 只翻当前展示的 25 条（未把 517 条全发出去）；切页 / 切语言**复用缓存，0 次新请求**
- 额度用尽时：界面文案**仍可切换**，25 条标题**全部保持原文**、无空标题、链接仍可点，且标注「当日额度已用尽」

### 5.3 仍未验证的一项（翻译质量）

译文**准确性未经人工评审**。MyMemory 是翻译记忆库，金融术语存在误译（§9.3 记录了三条实测样例）。
因此译文一律带 `MT` 标记，UI 不把它呈现为可信译文。此项需人工抽样评审后才能下结论。

---

## 6. 已知局限（写进 UI 与报告，不隐藏）

1. **非 tick 级**：轮询快照，equities/fx 10s、commodities 15s、crypto 5s、bonds 15min；不是交易所直连行情
2. **Yahoo 全线 429**：本机无法使用 Yahoo 系（含 yfinance），美股/商品走 sina·tencent·nasdaq，**覆盖面弱于 Yahoo**
3. **美股行情时间**：sina `gb_*` 的 `[3]` 实测为**北京时间**——与 `hf_*`、`sh*`、`fx_*` 同一时钟，
   已用同一时刻三路采样比对确认（`sh000001` 报 11:29:11、`hf_GC` 报 11:29:14，本机时钟 11:29:15；`gb_*` 同源）。
   该值指向**美股上一交易日的盘后/收盘时刻**：实测 `2026-09-19 08:14:43`（北京）= 2026-09-18 20:14 ET，
   即周五盘后收盘约 14 分钟后。与 A 股/加密的连续性不同，**跨资产不可直接比较涨跌幅的「当下性」**。
   （此前规格写作「美东盘后时间」有歧义，易被读成该值以美东时区表示，已按实测更正。）
4. **行情时间戳无时区标记**：sina 给的是**裸本地时间**（北京），UI 按浏览器本地时区解析；**同机访问正确**，
   异地浏览器访问会按当地时区解读这几个字段（新闻的 ISO 时间戳自带时区，不受影响）
5. **FX 买卖价不给**：`[5] [6]` 未获互证（USDCNY 点差异常），§2.2(d) 已剔除
6. **`nf_*` 国内期货未纳入**：昨结算索引未证实（§2.3）
7. **美债为日频**：`as_of` 通常是前一交易日，非实时
8. **新闻为标题级**：不做正文抽取（已评估 newspaper/trafilatura，见 §3），不保证时效排序的绝对准确
9. **无历史、无持久化**：进程重启即失去「最后有效值」
10. **新闻时间约 4% 为「假定时区」**：Investing.com 的 pubDate 无时区（实测 19/517），按 UTC 解析并以 `~` 标注；
    其余为 RFC822 / ISO8601，时区由端点给出（§2.2 g-2）
11. **加密为单主源**：binance 是唯一同时给出 24h 涨跌幅 + 高低 + 量的源；其余 5 个备源可达但字段更少，
    v1 未实现自动故障切换（失败即 `FEED DOWN`，不做降级拼凑）
12. **翻译额度是硬上限，且不覆盖全部新闻**：MyMemory 匿名额度 5000 字符/日（官方文档），
    仅约合 80 条标题，而全网现有 517 条。因此**只有当前展示的条目会被翻译**，滚动查看更多才会继续消耗额度；
    额度用尽后译文不再出现（显示原文 + 标注），**不会**用缓存以外的任何内容填充
13. **机翻质量有限**：MyMemory 为翻译记忆库，实测有金融术语误译（§9.3）；译文仅作阅读辅助，不构成交易依据
14. **翻译依赖单一第三方**：Google 端点本机 429、LibreTranslate 公共实例均已不可用（§9.1），
    MyMemory 是当前唯一可用端点；它不可用时翻译整体失效（界面文案切换不受影响）

---

## 7. 未决（需决定，不自行抹平）

| # | 未决项 | 现状 |
|---|---|---|
| U1 | 是否纳入国内期货 `nf_*`（需先证实昨结算字段） | 已探通端点，索引未证实 → v1 排除 |
| U2 | 是否加 Yahoo 备份源（需代理/换出口 IP 规避 429） | 本机 429，未验证规避方案 |
| U3 | 是否要分钟级 K 线 / 图表（引入 lightweight-charts 或自绘 canvas） | v1 不做，需确认再排期 |
| U4 | Bonds 是否扩展到欧元区/中国国债（ECB 曲线端点未测） | 未测，仅美国国债已证 |
| U5 | 是否需要持久化历史（SQLite）与导出 | v1 进程内，无落盘 |
| U6 | 是否用 `de` 邮箱参数把翻译额度提到 50000 字符/日 | 需用户决定是否把邮箱交给第三方；v1 按匿名 5000 字符/日 |

---

## 8. 文件结构

```
Dashboard/
├── SPEC-DASH.md              本规格
├── README.md                 使用说明
├── probe_sources.py          端点存活实测（51 个）      → data/probe_results.json
├── probe_github.py           仓库流行度实测             → data/github_popularity.json
├── probe_github_topics.py    topic 检索（降噪）         → data/github_topics.json
├── dump_fields.py            字段序位打印
├── verify_mapping.py         映射求解 + 跨源核对（一）
├── verify_mapping2.py        FX 双次采样差分 + 跨源核对（二）
├── capture_fixtures.py       抓取离线 fixture（结构不变、数值会变）
├── smoke_e2e.py              端到端自测（27 项，真起服务）
├── pytest.ini
├── .gitignore
├── qsdash/
│   ├── config.py             标的池 / 端点 / 刷新周期
│   ├── net.py                标准库 HTTP（重试·编码·溯源）
│   ├── markets.py            5 类资产适配器
│   ├── news.py               RSS 适配器（15 feed）
│   ├── hub.py                聚合 / 新鲜度 / 线程安全快照
│   ├── server.py             标准库 HTTP + SSE
│   ├── __main__.py           CLI: serve / check / snapshot
│   └── static/               index.html · terminal.css · terminal.js
├── tests/                    55 项离线单测 + fixtures/（真实样本 + 真实快照，逐位锁定字段索引）
├── smoke_client.js           客户端自测：jsdom 真跑 terminal.js（含翻译失败路径），40 项
├── probe_translate.py        翻译端点可用性实测（Google 429 / LibreTranslate 不可用）
├── probe_translate2.py       额度、限流、双向、边界实测
└── data/                     实测证据 + 运行缓存
    └── translation_cache.json  译文缓存 + 当日额度计数（重启不重复消耗额度）
```

---

## 9. 国际化与翻译：可行性实测与架构

### 9.1 端点实测（2026-09-21 本机）

| 端点 | 结果 | 判定 |
|---|---|---|
| Google 非官方 `translate_a/single`（client=gtx） | **HTTP 429**，10/10 次全失败 | **不可用**（与 Yahoo 同类：出口 IP 被限） |
| LibreTranslate 公共镜像 | `libretranslate.com` 400、`terraprint.co` 502、`lt.vern.cc` 307 | **不可用**（已收紧为需 key） |
| **MyMemory** `api.mymemory.translated.net/get` | **可用**，12/12 次成功 | **采用** |

MyMemory 实测数据：

| 指标 | 实测值 |
|---|---|
| 延迟 | min 1073ms / avg **1551ms** / max 2202ms（单条一次请求） |
| 连续 12 次请求 | 12 成功 / 0 失败，**未见限流** |
| 源语言 | `Autodetect` 与 `autodetect` **均可用**（EN→ZH 与 ZH→EN 均验证通过） |
| 额度字段 | 响应含 `quotaFinished`（可用于停止请求） |
| 空 query | HTTP 403 + 明确文案 |
| 译文样例 | `Fed holds rates steady as inflation cools` → `随着通胀降温，美联储维持利率稳定` |

### 9.2 额度硬约束（官方文档）

来源：`mymemory.translated.net/doc/usagelimits.php`
> "Free, anonymous usage is limited to **5000 chars/day**."
> "Provide a valid email ('de' parameter) … **50000 chars/day**."

按均值一条标题 ≈ 60 字符推算：

| 方案 | 字符量 | 是否可行 |
|---|---|---|
| 预翻全部 517 条 | ≈ 31,000 | **超出匿名额度 6.2 倍 → 不可能** |
| 只翻首屏 25 条 | ≈ 1,500 | 可行，占当日额度约 30% |
| 配合持久化缓存 | 同一条只花一次 | 反复切换语言**零额外消耗** |

→ 结论：**「翻译全部新闻」不可实现，也不应尝试**。v1 明确按需翻译 + 缓存 + 护栏。
带 `de` 邮箱参数可将额度提到 50000 字符/日，但等于把邮箱提供给第三方，属用户的隐私决定，
**v1 不实现**，列为未决 U6。

### 9.3 质量声明（不美化）

MyMemory 是**翻译记忆库**（TM）而非纯 MT：响应含 `match` 分数，译文可能来自用户贡献语料。
实测存在明显生硬处：

| 原文 | 译文 | 问题 |
|---|---|---|
| Oil climbs as OPEC signals deeper cuts | 石油输出国组织发出进一步减产信号，油价攀升 | 可接受 |
| Tesla deliveries miss estimates | 特斯拉的派送订单未达到预估 | "deliveries"（交付）误译为「派送订单」 |
| Gold hits record high on safe-haven demand | 黄金在避风港需求方面创下历史新高 | "safe-haven"（避险）误译为「避风港」 |
| US SECTORS CALL: Financials, … (真实在跑的标题) | 美国行业电话：金融、…… | "CALL"（电话会议）误译为「电话」，语义完全走偏 |

→ **UI 必须标注 `MT`**，不把机翻当作可信译文；金融术语存在误译，仅作阅读辅助。
