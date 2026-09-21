# QS-DASH — Dynamic Finance Dashboard

**English** · **[简体中文](README.zh-CN.md)**

A single-process, zero-dependency market terminal that runs in your browser: live prices for
**equities, FX, commodities, bonds and crypto**, plus **15 concurrent news feeds**, rendered in a
Bloomberg-terminal idiom — dark, amber, monospace, dense.

No `pip install`. No `npm install`. No API keys. Python 3 standard library and vanilla browser
APIs only.

```bash
cd Dashboard
python3 -m qsdash serve          # -> http://127.0.0.1:8848
```

---

## What you get

| Key | Page | Key | Page |
|---|---|---|---|
| `F1` | OVERVIEW (all five classes + news) | `F5` | BONDS |
| `F2` | EQUITIES | `F6` | CRYPTO |
| `F3` | FX | `F7` | NEWS |
| `F4` | COMMODITIES | `Esc` | back to OVERVIEW |

Deep links work: `http://127.0.0.1:8848/#CRYPTO`, and with a language prefix `#zh/CRYPTO`.
The page updates itself over Server-Sent Events — no manual refresh, no polling in the browser.

### Three commands

```bash
python3 -m qsdash serve              # the terminal
python3 -m qsdash check              # one-shot health check of all six feeds (exit 1 on failure)
python3 -m qsdash snapshot --json    # dump one full snapshot
```

---

## How it works — the logic

Everything follows from two constraints: **no dependencies**, and **never invent a number**.

```
scheduler thread (one interval per asset class)
  +- ThreadPoolExecutor ...... fetches all endpoints of a class concurrently
       +- markets.py / news.py . adapters: field mapping + cross-validation
            +- Hub ............ keeps last-known-good value + staleness age
                 +- snapshot()
                      +-> GET /api/snapshot     pull
                      +-> GET /api/stream       SSE push
```

Refresh intervals: crypto **5s** · equities **10s** · FX **10s** · commodities **15s** ·
news **90s** · bonds **900s** (the Treasury curve is a daily series — polling it faster is noise).

`net.fetch()` has one contract: **it never raises**. A failure returns `ok=False` plus the error
text. It retries network-layer errors, but never 4xx/5xx — an endpoint saying "no" is not jitter.

### Why no libraries

Chosen by crossing GitHub popularity against **whether the endpoint actually works from here**
(raw data in `data/github_popularity.json`):

| Library | Stars | Usable locally? | Verdict |
|---|---|---|---|
| OpenBB | 73,312 | needs its own backend, depends on Yahoo | not used |
| ccxt | 44,078 | works, but covers crypto only | reference only |
| yfinance | 25,301 | **no** — Yahoo returns 429 | not used |
| akshare | 22,662 | depends on East Money endpoints | not used |
| feedparser | 2,424 | `xml.etree` is already enough | not used |
| pandas-datareader | 3,269 | upstream sources are dead | not used |

The popular libraries were either unusable from this machine, or cost more in dependency risk than
they returned. Hence: **direct fetch plus a hand-maintained adapter layer**.

---

## The no-faking rule

This is the part that matters most, and it is enforced in code rather than in prose.

| Situation | What the system does |
|---|---|
| Endpoint returns nothing, or too few fields | the symbol goes into `skipped` **with a reason**, shown in the UI — **never filled with 0** |
| A number fails to parse | `None`, rendered `—` (`0` is a valid price and must not mean "missing") |
| A whole class fails | `ok=False`, raw error text shown, panel greyed out with `FEED DOWN` |
| ...but a previous value exists | that value is kept and labelled `STALE 42s` — never presented as live |
| Reported change % disagrees with `(last-prev)/prev` by more than 0.02pp | the computed value wins; the conflict is recorded in `extra.pct_conflict` |
| A news `pubDate` carries no timezone | parsed as UTC, flagged `tz_assumed`, UI prefixes the time with `~` |
| Translation quota is exhausted | the original text is shown with a label — **never an empty string or an invented translation** |

The UI never substitutes a plausible-looking number for a missing one. If you see `—`, the data
was not there.

---

## Data sources (measured, not assumed)

**40 of 51 candidate endpoints were reachable from the author's machine (2026-09-21).** These are
the ones actually wired in and verified by `qsdash check`:

| Class | Primary | Reachable backups | Typical rows |
|---|---|---|---|
| EQUITY | sina `gb_*` / `int_*` / `sh,sz` | tencent, api.nasdaq.com | 23 (12 US + 6 global index + 5 A-share index) |
| FX | sina `fx_*` | frankfurter, open.er-api, ECB | 8 pairs |
| COMMODITIES | sina `hf_*` | tencent `hf_*` | 12 |
| BONDS | US Treasury XML (nominal + real) | treasury fiscaldata | 17 (11 tenors + 4 TIPS + 2 spreads) |
| CRYPTO | binance `ticker/24hr` | coinbase / kraken / okx / bybit / coingecko | 10 |
| NEWS | 15 RSS feeds, fetched concurrently | — | 500+ after dedupe |

**Dead from this machine — do not retry:** Yahoo Finance (429 on every endpoint, including `^TNX`
and `GC=F`), stooq (404), FMP demo (401), FRED CSV (timeout), CoinDesk (308).

---

## Bilingual UI and news translation

The `EN | 中文` switch in the top bar changes the interface language **without reloading the
page**. The choice is stored in `localStorage` and can also be given in the URL (`#zh/CRYPTO`).
Ticker symbols and instrument names are **not** translated.

When the interface is Chinese, the **currently visible** news headlines are machine-translated and
tagged `MT`. Click the tag to flip between the translation and the original.

### Why only the visible ones

| Endpoint | Measured |
|---|---|
| Google unofficial `translate_a/single` | **HTTP 429**, 10 of 10 attempts — unusable |
| LibreTranslate public mirrors | 400 / 502 / 307 — unusable |
| **MyMemory** | **works**, 12 of 12, latency 1.07–2.20s |

MyMemory documents an anonymous quota of **5,000 characters per day**. The news pool is roughly
**500 headlines, about 31,000 characters — 6.2x over budget**. Translating everything up front is
not merely expensive; it is **impossible**. So the design is:

- translate only what is on screen (cap 30 per request), more only as you scroll;
- persist translations to `data/translation_cache.json`, so changing page or language costs **zero**;
- when the quota is nearly spent, or the provider reports `quotaFinished`, **stop requesting** and
  show the original text with a label;
- a dead translation service never affects prices or news rendering, and the interface language
  switch keeps working regardless.

### Translation quality, stated plainly

MyMemory is a translation **memory**, not a purpose-built MT engine. Observed on real headlines:

| Original | Translation | Problem |
|---|---|---|
| Tesla deliveries miss estimates | 特斯拉的派送订单未达到预估 | "deliveries" became "dispatch orders" |
| Gold hits record high on safe-haven demand | 黄金在避风港需求方面创下历史新高 | "safe-haven" became "harbour" |
| US SECTORS CALL: Financials, ... | 美国行业电话：金融、…… | "call" (earnings call) became "telephone" |

Translations are a **reading aid only**, never a trading input, and are always labelled `MT`.

---

## Tests

```bash
python3 -m pytest         # 55 offline unit tests — no network
python3 smoke_e2e.py      # 44 end-to-end: real server, real HTTP, real SSE, 3 real translations
node smoke_client.js      # 40 client tests in a real DOM (needs jsdom; see below)
python3 -m qsdash check   # full-stack health check
```

The offline tests replace `net.fetch` with fixtures captured from the **real** endpoints, which
lets the assertions pin **exact field indices**. That is the main regression guard here — the thing
most likely to be broken by an innocent-looking edit.

`smoke_client.js` runs the real `terminal.js` in a real DOM and deliberately exercises the
failure path: when the translation quota is exhausted, the interface must still switch language,
every headline must keep its original text, and no headline may render empty.

jsdom is **not** a dependency of this project — only this harness needs it. It is resolved from
`JSDOM_PATH`, then a global install, then a local `node_modules`. When it is absent the harness
prints `SKIPPED` and exits 0 instead of failing; the unit tests and `smoke_e2e.py` cover
everything else.

```bash
npm install -g jsdom
# or
JSDOM_PATH=/path/to/jsdom node smoke_client.js
```

---

## Known limitations

1. **Polled, not tick-level.** The fastest class is crypto at 5s; bonds are 900s. This is a snapshot
   terminal, not an exchange feed.
2. **"Freshness" is not comparable across classes.** US equity `quote_time` is the last close or
   after-hours stamp, while crypto is live. Each panel labels its own time; nothing is sorted onto a
   single timeline.
3. **Roughly 4% of news timestamps carry no timezone** (Investing.com publishes a naive local time).
   They are parsed as UTC and marked `~`.
4. **Bonds are daily.** `as_of` is usually the previous business day.
5. **FX bid/ask is omitted.** The quoted spread could not be reconciled with the last price (USDCNY
   off by 170bp), so it is left out rather than shown wrong.
6. **News is headline-level.** No article body extraction.
7. **No history and no persistence.** Only the last known good value is kept, in memory.
8. **China domestic futures are excluded.** The previous-settlement field for `nf_*` could not be
   reconciled (`nf_SC0` implied -6.7%), so v1 leaves them out.
9. **Translation is capped and therefore partial.** 5,000 characters per day covers roughly 80
   headlines; the pool is 500+.
10. **Machine translation is imperfect**, as shown above.
11. **Translation depends on one third party.** Google and LibreTranslate are unusable from here; if
    MyMemory goes down, translation stops. The interface language switch is unaffected.

Full evidence — including what could **not** be verified — is in `SPEC-DASH.md`. The specification
is written in Chinese and is the authoritative source for field mappings and acceptance criteria.

### Not yet verified

There is **no screenshot in this repository**. Capturing one headlessly was blocked on the author's
machine (Chromium's own sandbox cannot initialise there). Run the server and see it live: the layout
has been verified functionally, but its **appearance** has not been machine-checked.

---

## Layout

```
Dashboard/
├── qsdash/
│   ├── config.py       endpoints, universes, refresh intervals, 15 news feeds
│   ├── net.py          fetch layer — never raises, retries, gzip
│   ├── markets.py      five asset adapters, field mapping, cross-validation
│   ├── news.py         concurrent RSS, dedupe, three-format date parsing
│   ├── i18n.py         translation: on-demand, persistent cache, quota guard
│   ├── hub.py          scheduling, cache, last-known-good, snapshot assembly
│   ├── server.py       HTTP and SSE (stdlib ThreadingHTTPServer)
│   ├── __main__.py     CLI: serve / check / snapshot
│   └── static/         index.html · terminal.css · terminal.js (no external resources)
├── tests/              55 offline tests + fixtures captured from real endpoints
├── smoke_e2e.py        end-to-end
├── smoke_client.js     client-side, in a real DOM
├── SPEC-DASH.md        specification and measured evidence (Chinese)
└── data/               raw evidence: endpoint probe, GitHub star counts
```

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).
