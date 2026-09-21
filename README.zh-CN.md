# QS-DASH —— 动态金融终端

**[English](README.md)** · **简体中文**

一个单进程、零依赖的浏览器行情终端：**股票 / 外汇 / 大宗商品 / 债券 / 加密货币**五类资产实时价格，
叠加 **15 路并发新闻源**，以 Bloomberg 终端语义呈现（暗底、琥珀色、等宽、高密度）。

不用 `pip install`，不用 `npm install`，不需要任何 API key。只用 Python 3 标准库与原生浏览器 API。

```bash
cd Dashboard
python3 -m qsdash serve          # -> http://127.0.0.1:8848
```

---

## 你会看到什么

| 键 | 页面 | 键 | 页面 |
|---|---|---|---|
| `F1` | OVERVIEW（五类资产 + 新闻） | `F5` | BONDS |
| `F2` | EQUITIES | `F6` | CRYPTO |
| `F3` | FX | `F7` | NEWS |
| `F4` | COMMODITIES | `Esc` | 回到 OVERVIEW |

支持直链：`http://127.0.0.1:8848/#CRYPTO`，也可带语言前缀 `#zh/CRYPTO`。
页面通过 Server-Sent Events 自行推送更新——不需要手动刷新，浏览器侧不做轮询。

### 三条命令

```bash
python3 -m qsdash serve              # 启动终端
python3 -m qsdash check              # 一次性体检六类数据源（任一失败则退出码 1）
python3 -m qsdash snapshot --json    # 打印一份完整快照
```

---

## 它是怎么运作的（核心逻辑）

整个设计只由两条约束推出：**不引入依赖**，以及**绝不编造数字**。

```
调度线程（每类资产一个刷新周期）
  +- ThreadPoolExecutor ...... 并发抓取同一类的全部端点
       +- markets.py / news.py . 适配器：字段映射 + 交叉校验
            +- Hub ............ 保留「最后一次有效值」与陈旧年龄
                 +- snapshot()
                      +-> GET /api/snapshot     拉取
                      +-> GET /api/stream       SSE 推送
```

刷新周期：加密 **5s** · 股票 **10s** · 外汇 **10s** · 大宗商品 **15s** · 新闻 **90s** ·
债券 **900s**（美债收益率曲线是日频序列，轮询更快只是噪声）。

`net.fetch()` 只有一条契约：**永不抛异常**。失败以 `ok=False` 加错误原文返回。
它只对网络层错误重试，4xx/5xx **不重试**——端点明确说「不」，那不是抖动。

### 为什么不用现成的库

判断方式是「GitHub 流行度 × **在本机到底能不能跑通**」两者交叉（原始数据见
`data/github_popularity.json`）：

| 库 | ★ | 本机可用性 | 结论 |
|---|---|---|---|
| OpenBB | 73,312 | 需自建后端，依赖 Yahoo | 不采用 |
| ccxt | 44,078 | 可用，但只覆盖加密一类 | 仅参考 |
| yfinance | 25,301 | **不可用**——Yahoo 返回 429 | 不采用 |
| akshare | 22,662 | 依赖东方财富接口 | 不采用 |
| feedparser | 2,424 | `xml.etree` 已经够用 | 不采用 |
| pandas-datareader | 3,269 | 上游数据源已失效 | 不采用 |

流行库要么在本机根本跑不通，要么引入的依赖风险高于它带来的收益。
所以走的是**直连端点 + 自己维护的适配层**。

---

## 不造假规则

这是整个项目最要紧的部分，而且它是**由代码保证的，不是靠文档承诺**。

| 情况 | 系统的处理 |
|---|---|
| 端点返回空、或字段不足 | 该标的进入 `skipped` 并**附带原因**，页面明示——**绝不填 0** |
| 数字解析失败 | `None`，界面渲染为 `—`（`0` 是有效行情，不能拿来表示「缺失」） |
| 整类数据源失败 | `ok=False` + 错误原文，面板置灰并显示 `FEED DOWN` |
| 但此前有有效值 | 保留该值并标注 `STALE 42s`——绝不当作实时值呈现 |
| 端点给的涨跌幅与 `(last-prev)/prev` 相差超过 0.02pp | 以自算值为准，冲突记录在 `extra.pct_conflict` |
| 新闻 `pubDate` 不带时区 | 按 UTC 解析并置 `tz_assumed`，界面在时间前加 `~` |
| 翻译额度用尽 | 显示原文并加标注——**绝不返回空串，也绝不编造译文** |

界面**永远不会**用「看起来合理」的数字填补缺失值。你看到 `—`，就说明那个数据当时真的没有。

---

## 数据源（实测，不是推断）

**51 个候选端点中 40 个在作者本机可达（2026-09-21）。** 以下是真正接入、并由 `qsdash check` 验证的：

| 资产类 | 主源 | 可达备用源 | 典型条数 |
|---|---|---|---|
| EQUITY | sina `gb_*` / `int_*` / `sh,sz` | tencent、api.nasdaq.com | 23（美股 12 + 全球指数 6 + A 股指数 5） |
| FX | sina `fx_*` | frankfurter、open.er-api、ECB | 8 对 |
| COMMODITIES | sina `hf_*` | tencent `hf_*` | 12 |
| BONDS | 美国财政部 XML（名义 + 实际） | treasury fiscaldata | 17（11 个期限 + 4 个 TIPS + 2 个利差） |
| CRYPTO | binance `ticker/24hr` | coinbase / kraken / okx / bybit / coingecko | 10 |
| NEWS | 15 路 RSS 并发抓取 | — | 去重后 500+ 条 |

**本机不可用、不要重试的源**：Yahoo Finance（全系 429，含 `^TNX`、`GC=F`）、stooq（404）、
FMP demo（401）、FRED CSV（超时）、CoinDesk（308）。

---

## 中英双语界面与新闻翻译

顶栏的 `EN | 中文` 开关可切换界面语言，**不刷新页面**；选择记在 `localStorage`，
也可由 URL 指定（`#zh/CRYPTO`）。**行情代码与标的名称不翻译**。

界面切到中文时，**当前展示的**新闻标题会被机器翻译并标注 `机翻`；
点这个标记即可在译文与原文之间切换。

### 为什么只翻「当前展示的」

| 端点 | 实测结果 |
|---|---|
| Google 非官方 `translate_a/single` | **HTTP 429**，10/10 全失败——不可用 |
| LibreTranslate 公共镜像 | 400 / 502 / 307——不可用 |
| **MyMemory** | **可用**，12/12 成功，延迟 1.07–2.20s |

MyMemory 官方标注的匿名额度是 **5000 字符/日**。而新闻池约 **500 条 ≈ 31,000 字符，超额度 6.2 倍**。
所以「一次性全部翻好」不是**贵**的问题，而是**做不到**。因此设计成：

- 只翻屏幕上正在显示的条目（单次上限 30 条），滚动查看更多才会继续消耗；
- 译文持久化到 `data/translation_cache.json`，**切页、切语言都零额外消耗**；
- 额度将尽、或 provider 回报 `quotaFinished` 时**立即停止请求**，显示原文并加标注；
- 翻译服务挂掉**不影响行情与新闻渲染**，界面语言切换也**不依赖**它。

### 关于翻译质量，直说

MyMemory 是**翻译记忆库**，不是专门的机器翻译引擎。以下是真实标题上的实测结果：

| 原文 | 译文 | 问题 |
|---|---|---|
| Tesla deliveries miss estimates | 特斯拉的派送订单未达到预估 | deliveries（交付）被译成「派送订单」 |
| Gold hits record high on safe-haven demand | 黄金在避风港需求方面创下历史新高 | safe-haven（避险）被译成「避风港」 |
| US SECTORS CALL: Financials, ... | 美国行业电话：金融、…… | call（电话会议）被译成「电话」 |

译文**仅作阅读辅助**，不构成任何交易依据，且始终带 `机翻` 标记。

---

## 测试

```bash
python3 -m pytest         # 55 项离线单测——不打网络
python3 smoke_e2e.py      # 44 项端到端：真起服务、真打 HTTP、真读 SSE、真实翻译 3 条
node smoke_client.js      # 40 项客户端自测：在真实 DOM 中执行（需 jsdom，见下）
python3 -m qsdash check   # 全链路体检
```

离线单测把 `net.fetch` 换成从**真实端点**抓回来的样本，因此断言可以**逐位锁定字段索引**。
这是本项目最主要的回归护栏——也是「看着无害的一次改动」最容易改坏的地方。

`smoke_client.js` 在真实 DOM 里运行真实的 `terminal.js`，并且刻意覆盖失败路径：
翻译额度用尽时，界面仍须能切换语言、每条标题必须保持原文、且不得有任何标题渲染为空。

jsdom **不是**本项目的依赖，只有这个 harness 需要它。查找顺序为 `JSDOM_PATH` → 全局安装 →
本地 `node_modules`；找不到时打印 `SKIPPED` 并以退出码 0 结束，不判失败。
其余部分由离线单测与 `smoke_e2e.py` 覆盖。

```bash
npm install -g jsdom
# 或
JSDOM_PATH=/path/to/jsdom node smoke_client.js
```

---

## 已知限制

1. **轮询，不是逐笔。** 最快的一类是加密 5s，债券 900s。这是快照终端，不是交易所行情源。
2. **跨资产的「新鲜度」不可比。** 美股 `quote_time` 是上一交易日的收盘／盘后时刻，加密则是实时的。
   各面板各自标注自己的时间，不做统一时间轴排序。
3. **约 4% 的新闻时间戳没有时区**（Investing.com 给的是无时区裸时间），按 UTC 解析并以 `~` 标注。
4. **债券是日频。** `as_of` 通常是上一交易日。
5. **不展示外汇买卖价。** 端点给的价差与最新价无法互证（USDCNY 差 170bp），宁可少给也不给错的。
6. **新闻只到标题级。** 不做正文抽取。
7. **无历史、无持久化。** 只在内存里保留「最后一次有效值」。
8. **国内期货未纳入。** `nf_*` 的「昨结」字段无法互证（`nf_SC0` 隐含 -6.7%），v1 排除。
9. **翻译受额度限制，因此只能是部分的。** 5000 字符/日约合 80 条标题，而新闻池有 500+ 条。
10. **机器翻译质量有限**，见上方实测样例。
11. **翻译依赖单一第三方。** Google 与 LibreTranslate 在本机均不可用；MyMemory 若不可用，
    翻译即整体失效（界面语言切换不受影响）。

包含「**未能验证**」部分的完整证据在 `SPEC-DASH.md`——那是本项目字段映射与验收标准的真源。

### 尚未验证的部分

仓库里**没有截图**。作者本机无法做无头截图（Chromium 自身的沙箱在该环境下无法初始化）。
请直接跑起来看：布局已通过功能验证，但它的**外观**没有被机器检查过。

---

## 目录结构

```
Dashboard/
├── qsdash/
│   ├── config.py       端点 / 标的池 / 刷新周期 / 15 路新闻源
│   ├── net.py          抓取层——永不抛异常、带重试与 gzip
│   ├── markets.py      五类资产适配器、字段映射、交叉校验
│   ├── news.py         RSS 并发、去重、三种时间格式解析
│   ├── i18n.py         翻译：按需 + 持久化缓存 + 额度护栏
│   ├── hub.py          调度、缓存、last-known-good、快照组装
│   ├── server.py       HTTP 与 SSE（标准库 ThreadingHTTPServer）
│   ├── __main__.py     CLI：serve / check / snapshot
│   └── static/         index.html · terminal.css · terminal.js（无外部资源）
├── tests/              55 项离线单测 + 从真实端点抓回的 fixtures
├── smoke_e2e.py        端到端自测
├── smoke_client.js     客户端自测（真实 DOM）
├── SPEC-DASH.md        规格与实测证据（真源）
└── data/               原始证据：端点探针、GitHub 星标数
```

---

## 许可

Apache License 2.0 —— 见 [LICENSE](LICENSE)。
