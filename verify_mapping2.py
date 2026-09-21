#!/usr/bin/env python3
"""续：FX 用"两次采样差值"定位实时字段；并补完商品/美债/加密/新闻的核对。"""
import json, ssl, time, urllib.request, xml.etree.ElementTree as ET

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
     "Referer": "https://finance.sina.com.cn"}

def get(url, hdrs=None, enc="utf-8"):
    h = dict(H); h.update(hdrs or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20, context=CTX) as r:
        return r.read().decode(enc, "replace")

def sina(sym):
    raw = get("https://hq.sinajs.cn/list=" + sym, enc="gbk")
    out = {}
    for line in raw.strip().split("\n"):
        if "=" not in line: continue
        k, _, v = line.partition("=")
        out[k.replace("var hq_str_", "").strip()] = v.strip().strip(";").strip('"').split(",")
    return out

SYM = ["fx_susdcny", "fx_seurusd", "fx_susdjpy", "fx_sgbpusd"]
print("### 1. FX 双次采样：字段是否在 25 秒内变动（变动=实时字段，不动=参考值）")
a = sina(",".join(SYM))
time.sleep(25)
b = sina(",".join(SYM))
for k in SYM:
    fa, fb = a.get(k, []), b.get(k, [])
    if len(fa) != len(fb):
        print("  %-14s 字段数不一致 %d vs %d" % (k, len(fa), len(fb))); continue
    moved = [(i, fa[i], fb[i]) for i in range(len(fa)) if fa[i] != fb[i]]
    still = [i for i in range(len(fa)) if fa[i] == fb[i] and fa[i].strip()]
    print("  %-14s 变动字段: %s" % (k, ", ".join("[%d] %s->%s" % m for m in moved) or "无"))
    print("  %-14s 静止字段(非空): %s" % ("", ", ".join("[%d]=%s" % (i, fa[i][:14]) for i in still)))

print("\n" + "="*78)
print("### 2. 商品 hf_ 交叉核对（sina vs tencent）")
t = {}
for line in get("https://qt.gtimg.cn/q=hf_GC,hf_CL,hf_SI,hf_HG,hf_NG,hf_C,hf_S,hf_W").strip().split("\n"):
    if "=" not in line: continue
    k, _, v = line.partition("=")
    t[k.strip().replace("v_hf_", "").replace('"', '')] = v.strip().strip(";").strip('"').split(",")
for name, f in sina("hf_GC,hf_CL,hf_SI,hf_HG,hf_NG,hf_C,hf_S,hf_W").items():
    sym = name.replace("hf_", ""); tx = t.get(sym)
    if not tx or len(tx) < 8: print("  %-10s tencent 无数据" % name); continue
    last, prevs = float(f[0]), float(f[7])
    calc = (last - prevs) / prevs * 100
    print("  %-10s name=%-8s sina[0]=%-10s sina[7]prevs=%-9s pct=%+.3f%% | tencent[0]=%-10s [1]pct=%-7s 一致=%s"
          % (name, f[13], last, prevs, calc, tx[0], tx[1], abs(calc - float(tx[1])) < 0.05))

print("\n" + "="*78)
print("### 3. 上期所 nf_ 字段核对")
for name, f in sina("nf_AU0,nf_AG0,nf_CU0,nf_SC0,nf_RB0").items():
    print("  %-10s %-8s [2]开盘=%-9s [3]高=%-9s [4]低=%-9s [8]最新=%-9s [10]=%-9s [27]=%-9s"
          % (name, f[0], f[2], f[3], f[4], f[8], f[10], f[27]))

print("\n" + "="*78)
print("### 4. 美债曲线 XML")
x = get("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
        "?data=daily_treasury_yield_curve&field_tdr_date_value=2026")
root = ET.fromstring(x); rows = []
for entry in root.iter():
    if not entry.tag.endswith("entry"): continue
    rec = {}
    for p in entry.iter():
        tag = p.tag.split("}")[-1]
        if tag.startswith("BC_") or tag == "NEW_DATE": rec[tag] = (p.text or "").strip()
    if rec: rows.append(rec)
rows.sort(key=lambda r: r.get("NEW_DATE", ""))
print("  entries=%d 首=%s 末=%s" % (len(rows), rows[0]["NEW_DATE"], rows[-1]["NEW_DATE"]))
print("  最新: " + "  ".join("%s=%s" % (k.replace("BC_", ""), v) for k, v in sorted(rows[-1].items()) if k != "NEW_DATE"))
ABBR = ["DGS1MO","DGS3MO","DGS6MO","DGS1","DGS2","DGS3","DGS5","DGS7","DGS10","DGS20","DGS30"]
print("\n### 5. 债券历史：能否从 XML 直接取到久期序列（用于利差）")
d = rows[-1]
print("  10Y-2Y 利差 = %.3f" % (float(d["BC_10YEAR"]) - float(d["BC_2YEAR"])))
print("  10Y-3M 利差 = %.3f" % (float(d["BC_10YEAR"]) - float(d["BC_3MONTH"])))

print("\n" + "="*78)
print("### 6. 加密跨源一致性")
def j(url, hdrs=None): return json.loads(get(url, hdrs))
vals = {}
for lbl, fn in [
    ("binance", lambda: j("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT")["lastPrice"]),
    ("coinbase", lambda: j("https://api.exchange.coinbase.com/products/BTC-USD/ticker", {"User-Agent": "curl/8.0"})["price"]),
    ("kraken", lambda: j("https://api.kraken.com/0/public/Ticker?pair=XBTUSD")["result"]["XXBTZUSD"]["c"][0]),
    ("coingecko", lambda: str(j("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd")["bitcoin"]["usd"])),
    ("okx", lambda: j("https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT")["data"][0]["last"]),
    ("bybit", lambda: j("https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT")["result"]["list"][0]["lastPrice"]),
]:
    try: vals[lbl] = float(fn())
    except Exception as e: print("  %-10s ERR %s" % (lbl, str(e)[:70]))
lo, hi = min(vals.values()), max(vals.values())
print("  " + "  ".join("%s=%.2f" % (k, v) for k, v in vals.items()))
print("  极差=%.2f (%.4f%%)  —— 跨源应在 0.3%% 内" % (hi - lo, (hi - lo) / lo * 100))

print("\n" + "="*78)
print("### 7. 新闻 RSS 结构")
for label, url in [("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
                   ("GoogleNews", "https://news.google.com/rss/search?q=stock+market+when:1d&hl=en-US&gl=US&ceid=US:en"),
                   ("CoinTelegraph", "https://cointelegraph.com/rss"),
                   ("Investing", "https://www.investing.com/rss/news.rss"),
                   ("FT", "https://www.ft.com/rss/home"),
                   ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
                   ("BBC", "https://feeds.bbci.co.uk/news/business/rss.xml"),
                   ("YahooFin", "https://finance.yahoo.com/news/rssindex")]:
    try:
        root = ET.fromstring(get(url)); items = root.findall(".//item")
        def n(tag): return sum(1 for i in items if (i.findtext(tag) or "").strip())
        print("  %-13s n=%-4d title=%-4d link=%-4d date=%-4d src=%-4d | %s"
              % (label, len(items), n("title"), n("link"), n("pubDate"), n("source"),
                 (items[0].findtext("title") or "")[:56] if items else ""))
    except Exception as e:
        print("  %-13s ERR %s" % (label, str(e)[:70]))
