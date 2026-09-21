#!/usr/bin/env python3
"""字段映射实证：用内部一致性与跨源交叉核对，把索引"解"出来，而不是靠记忆断言。
每个结论都能在此脚本里被复现。"""
import json, ssl, urllib.request, xml.etree.ElementTree as ET

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

print("="*78)
print("### 1. FX 索引求解：在 18 个字段里搜索满足 (cur-prev)/prev*100 == 涨跌幅 的配对")
fx = sina("fx_susdcny,fx_seurusd,fx_susdjpy,fx_sgbpusd,fx_saudusd,fx_susdchf,fx_susdcad,fx_susdcnh")
for name, f in fx.items():
    try:
        pct, chg = float(f[10]), float(f[11])
    except Exception:
        print("  %-14s 涨跌幅/涨跌额不可解析" % name); continue
    hits = []
    for i in range(len(f)):
        for j in range(len(f)):
            if i == j: continue
            try: cur, prev = float(f[i]), float(f[j])
            except Exception: continue
            if prev == 0: continue
            if abs((cur - prev) - chg) < max(1e-6, abs(chg) * 2e-3) and \
               abs((cur - prev) / prev * 100 - pct) < 1e-3:
                hits.append((i, j, cur, prev))
    print("  %-14s pct=%-9s chg=%-10s 解: %s" % (name, pct, chg,
          "  ".join("cur[%d]=%s prev[%d]=%s" % h for h in hits) or "*** 无解 ***"))

print("\n" + "="*78)
print("### 2. 美股 gb_ 一致性：([1] - [26]) / [26] * 100  是否等于 [2]？")
for name, f in sina("gb_aapl,gb_msft,gb_nvda,gb_tsla,gb_amzn").items():
    last, pct, chg, prev26, prev35 = float(f[1]), float(f[2]), float(f[4]), float(f[26]), float(f[35])
    calc = (last - prev26) / prev26 * 100
    print("  %-9s last=%-10s prev[26]=%-10s prev[35]=%-10s  算得=%.4f%%  端点[2]=%.2f%%  chg[4]=%s  一致=%s"
          % (name, last, prev26, prev35, calc, pct, chg, abs(calc - pct) < 0.01))

print("\n" + "="*78)
print("### 3. 全球指数 int_ 一致性：[2] 是否等于 [1] * [3]/100")
for name, f in sina("int_dji,int_nasdaq,int_sp500,int_hangseng,int_nikkei,int_ftse,int_dax").items():
    last, chg, pct = float(f[1]), float(f[2]), float(f[3])
    prev = last - chg
    print("  %-12s last=%-12s chg=%-10s pct=%-8s  算得=%.4f%% 一致=%s"
          % (name, last, chg, pct, chg / prev * 100 if prev else 0, abs(chg / prev * 100 - pct) < 0.02))

print("\n" + "="*78)
print("### 4. 商品 hf_ 交叉核对：sina [0] vs tencent [0]，以及 pct 是否 = ([0]-[7])/[7]")
t = {}
for line in get("https://qt.gtimg.cn/q=hf_GC,hf_CL,hf_SI,hf_HG,hf_NG").strip().split("\n"):
    if "=" not in line: continue
    k, _, v = line.partition("=")
    t[k.strip().replace("v_", "").replace('"', '').split("_")[-1]] = v.strip().strip(";").strip('"').split(",")
s = sina("hf_GC,hf_CL,hf_SI,hf_HG,hf_NG")
for name, f in s.items():
    sym = name.replace("hf_", "")
    last, prevs = float(f[0]), float(f[7])
    calc = (last - prevs) / prevs * 100
    tx = t.get(sym)
    tpct = float(tx[1]) if tx and tx[1] not in ("",) else None
    print("  %-10s sina[0]=%-11s sina[7]=%-11s 算得pct=%+.4f%%  tencent pct=%-8s 价格差=%.4f 一致=%s"
          % (name, last, prevs, calc, tpct, abs(last - float(tx[0])) if tx else -1,
             tpct is not None and abs(calc - tpct) < 0.02))

print("\n" + "="*78)
print("### 5. 上期所 nf_ 一致性：([8] - [10]) / [10] * 100")
for name, f in sina("nf_AU0,nf_AG0,nf_CU0,nf_SC0,nf_RB0").items():
    print("  %-10s name=%-8s [2]open=%-9s [3]high=%-9s [4]low=%-9s [8]last=%-9s [10]=%-9s [27]=%-9s"
          % (name, f[0], f[2], f[3], f[4], f[8], f[10], f[27]))

print("\n" + "="*78)
print("### 6. 美债 XML 解析（去掉命名空间）")
x = get("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
        "?data=daily_treasury_yield_curve&field_tdr_date_value=2026")
root = ET.fromstring(x)
rows = []
for entry in root.iter():
    if not entry.tag.endswith("entry"): continue
    rec = {}
    for p in entry.iter():
        tag = p.tag.split("}")[-1]
        if tag in ("NEW_DATE", "BC_1MONTH", "BC_3MONTH", "BC_6MONTH", "BC_1YEAR", "BC_2YEAR",
                   "BC_3YEAR", "BC_5YEAR", "BC_7YEAR", "BC_10YEAR", "BC_20YEAR", "BC_30YEAR"):
            rec[tag] = (p.text or "").strip()
    if rec: rows.append(rec)
rows.sort(key=lambda r: r.get("NEW_DATE", ""))
print("  entries=%d  首=%s  末=%s" % (len(rows), rows[0]["NEW_DATE"], rows[-1]["NEW_DATE"]))
last = rows[-1]
for k in ["BC_1MONTH","BC_3MONTH","BC_6MONTH","BC_1YEAR","BC_2YEAR","BC_3YEAR","BC_5YEAR","BC_7YEAR","BC_10YEAR","BC_20YEAR","BC_30YEAR"]:
    print("   %-10s %s" % (k, last.get(k)))

print("\n" + "="*78)
print("### 7. 加密跨源一致性（BTC 现货，分钟级不同源应互相接近）")
def j(url, hdrs=None):
    return json.loads(get(url, hdrs))
try:
    b = j("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT"); print("  binance    last=%s pct=%s" % (b["lastPrice"], b["priceChangePercent"]))
except Exception as e: print("  binance    ERR", e)
try:
    c = j("https://api.exchange.coinbase.com/products/BTC-USD/ticker", {"User-Agent": "curl/8.0"}); print("  coinbase   last=%s" % c["price"])
except Exception as e: print("  coinbase   ERR", e)
try:
    k = j("https://api.kraken.com/0/public/Ticker?pair=XBTUSD"); print("  kraken     last=%s" % k["result"]["XXBTZUSD"]["c"][0])
except Exception as e: print("  kraken     ERR", e)
try:
    g = j("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true"); print("  coingecko  last=%s pct=%.3f" % (g["bitcoin"]["usd"], g["bitcoin"]["usd_24h_change"]))
except Exception as e: print("  coingecko  ERR", e)
try:
    o = j("https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT"); print("  okx        last=%s" % o["data"][0]["last"])
except Exception as e: print("  okx        ERR", e)
try:
    y = j("https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT"); print("  bybit      last=%s pct=%s" % (y["result"]["list"][0]["lastPrice"], y["result"]["list"][0]["price24hPcnt"]))
except Exception as e: print("  bybit      ERR", e)

print("\n" + "="*78)
print("### 8. 新闻 RSS 解析（结构 + 条数 + 字段完整性）")
for label, url in [("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
                   ("GoogleNews", "https://news.google.com/rss/search?q=stock+market+when:1d&hl=en-US&gl=US&ceid=US:en"),
                   ("CoinTelegraph", "https://cointelegraph.com/rss"),
                   ("Investing", "https://www.investing.com/rss/news.rss"),
                   ("FT", "https://www.ft.com/rss/home")]:
    try:
        root = ET.fromstring(get(url))
        items = root.findall(".//item")
        n_t = sum(1 for i in items if (i.findtext("title") or "").strip())
        n_l = sum(1 for i in items if (i.findtext("link") or "").strip())
        n_d = sum(1 for i in items if (i.findtext("pubDate") or "").strip())
        n_s = sum(1 for i in items if (i.findtext("source") or "").strip())
        print("  %-14s items=%-4d title=%d link=%d pubDate=%d source=%d" % (label, len(items), n_t, n_l, n_d, n_s))
        if items: print("      sample: %s" % (items[0].findtext("title") or "")[:88])
    except Exception as e:
        print("  %-14s ERR %s" % (label, e))
