#!/usr/bin/env python3
"""数据源可行性实测（可证伪的小脚本，SPEC-DASH §2 的依据）。

只做一件事：对每个候选端点发一次 GET，记录 状态码/耗时/字节数/样本。
不做推断——不通就是不通，不降级、不兜底、不用假数据填位。
用法: python3 probe_sources.py    输出: data/probe_results.json + 控制台矩阵
"""
import json, os, ssl, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
TIMEOUT = 15
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
SINA_REF = {"Referer": "https://finance.sina.com.cn"}

TARGETS = [
 ("EQUITY","yahoo_chart_q1","https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d",{}),
 ("EQUITY","yahoo_chart_q2","https://query2.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d",{}),
 ("EQUITY","stooq_csv","https://stooq.com/q/l/?s=aapl.us&f=sd2t2ohlcv&e=csv",{}),
 ("EQUITY","stooq_pl","https://stooq.pl/q/l/?s=aapl.us&f=sd2t2ohlcv&e=csv",{}),
 ("EQUITY","sina_us_multi","https://hq.sinajs.cn/list=gb_aapl,gb_msft,gb_nvda",SINA_REF),
 ("EQUITY","sina_int_idx","https://hq.sinajs.cn/list=int_dji,int_nasdaq,int_sp500,int_hangseng,int_nikkei,int_ftse,int_dax",SINA_REF),
 ("EQUITY","sina_cn_idx","https://hq.sinajs.cn/list=sh000001,sz399001,sz399006,sh000300",SINA_REF),
 ("EQUITY","tencent_us_multi","https://qt.gtimg.cn/q=usAAPL,usMSFT,usNVDA",{}),
 ("EQUITY","fmp_demo","https://financialmodelingprep.com/api/v3/quote/AAPL?apikey=demo",{}),
 ("EQUITY","nasdaq_api","https://api.nasdaq.com/api/quote/AAPL/info?assetclass=stocks",{}),
 ("FX","sina_fx_majors","https://hq.sinajs.cn/list=fx_susdcny,fx_seurusd,fx_susdjpy,fx_sgbpusd,fx_saudusd,fx_susdcnh,fx_susdchf,fx_susdcad",SINA_REF),
 ("FX","tencent_fx","https://qt.gtimg.cn/q=fx_susdcny",{}),
 ("FX","frankfurter","https://api.frankfurter.app/latest?from=USD&to=EUR,JPY,GBP,CNY,CHF,CAD,AUD",{}),
 ("FX","er_api","https://open.er-api.com/v6/latest/USD",{}),
 ("FX","ecb_daily_xml","https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",{}),
 ("FX","yahoo_fx","https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?range=1d&interval=1d",{}),
 ("CMDTY","sina_hf_energy","https://hq.sinajs.cn/list=hf_CL,hf_NG,hf_HO,hf_RB",SINA_REF),
 ("CMDTY","sina_hf_metals","https://hq.sinajs.cn/list=hf_GC,hf_SI,hf_HG,hf_PL,hf_PA",SINA_REF),
 ("CMDTY","sina_hf_ags","https://hq.sinajs.cn/list=hf_C,hf_S,hf_W,hf_ZC,hf_ZS,hf_CT,hf_KC,hf_SB,hf_CC",SINA_REF),
 ("CMDTY","sina_nf_shfe","https://hq.sinajs.cn/list=nf_AU0,nf_AG0,nf_CU0,nf_SC0,nf_RB0",SINA_REF),
 ("CMDTY","tencent_hf","https://qt.gtimg.cn/q=hf_GC,hf_CL",{}),
 ("CMDTY","yahoo_gold","https://query1.finance.yahoo.com/v8/finance/chart/GC=F?range=1d&interval=1d",{}),
 ("CMDTY","stooq_gold","https://stooq.com/q/l/?s=gc.f&f=sd2t2ohlcv&e=csv",{}),
 ("BOND","treasury_nominal","https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=2026",{}),
 ("BOND","treasury_real","https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_real_yield_curve&field_tdr_date_value=2026",{}),
 ("BOND","fred_dgs10","https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",{}),
 ("BOND","fred_dgs30","https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS30",{}),
 ("BOND","yahoo_tnx","https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?range=1d&interval=1d",{}),
 ("BOND","fiscaldata","https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates?sort=-record_date&page[size]=5",{}),
 ("CRYPTO","binance_24hr","https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT",{}),
 ("CRYPTO","binance_multi","https://api.binance.com/api/v3/ticker/24hr?symbols=%5B%22BTCUSDT%22,%22ETHUSDT%22%5D",{}),
 ("CRYPTO","coinbase_tkr","https://api.exchange.coinbase.com/products/BTC-USD/ticker",{"User-Agent":"curl/8.0"}),
 ("CRYPTO","coingecko_mkt","https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=10&page=1&price_change_percentage=24h",{}),
 ("CRYPTO","kraken_tkr","https://api.kraken.com/0/public/Ticker?pair=XBTUSD,ETHUSD",{}),
 ("CRYPTO","okx_tickers","https://www.okx.com/api/v5/market/tickers?instType=SPOT",{}),
 ("CRYPTO","bybit_tickers","https://api.bybit.com/v5/market/tickers?category=spot",{}),
 ("NEWS","cnbc_top","https://www.cnbc.com/id/100003114/device/rss/rss.html",{}),
 ("NEWS","cnbc_markets","https://www.cnbc.com/id/20910258/device/rss/rss.html",{}),
 ("NEWS","marketwatch","https://feeds.content.dowjones.io/public/rss/mw_topstories",{}),
 ("NEWS","yahoo_finance","https://finance.yahoo.com/news/rssindex",{}),
 ("NEWS","investing_news","https://www.investing.com/rss/news.rss",{}),
 ("NEWS","investing_econ","https://www.investing.com/rss/news_14.rss",{}),
 ("NEWS","coindesk_alt","https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml",{}),
 ("NEWS","cointelegraph","https://cointelegraph.com/rss",{}),
 ("NEWS","theblock","https://www.theblock.co/rss.xml",{}),
 ("NEWS","decrypt","https://decrypt.co/feed",{}),
 ("NEWS","ft_home","https://www.ft.com/rss/home",{}),
 ("NEWS","bbc_business","https://feeds.bbci.co.uk/news/business/rss.xml",{}),
 ("NEWS","google_news_mkt","https://news.google.com/rss/search?q=stock+market+when:1d&hl=en-US&gl=US&ceid=US:en",{}),
 ("NEWS","seekingalpha","https://seekingalpha.com/market_currents.xml",{}),
 ("NEWS","zerohedge","https://feeds.feedburner.com/zerohedge/feed",{}),
 ("NEWS","reuters_gnews","https://news.google.com/rss/search?q=when:1d+site:reuters.com+business&hl=en-US&gl=US&ceid=US:en",{}),
]

def probe(t):
    ac, name, url, hdrs = t
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
    h.update(hdrs)
    t0 = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=TIMEOUT, context=CTX) as r:
            body = r.read()
            return {"asset_class": ac, "name": name, "url": url, "ok": True, "status": r.status,
                    "ms": int((time.time()-t0)*1000), "bytes": len(body),
                    "ctype": r.headers.get("Content-Type",""),
                    "sample": body[:160].decode("utf-8","replace").replace("\n"," ")}
    except urllib.error.HTTPError as e:
        return {"asset_class": ac, "name": name, "url": url, "ok": False, "status": e.code,
                "ms": int((time.time()-t0)*1000), "bytes": 0, "ctype": "", "error": "HTTP %s" % e.code}
    except Exception as e:
        return {"asset_class": ac, "name": name, "url": url, "ok": False, "status": None,
                "ms": int((time.time()-t0)*1000), "bytes": 0, "ctype": "",
                "error": "%s: %s" % (type(e).__name__, str(e)[:100])}

def main():
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(probe, TARGETS))
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "probe_results.json"), "w") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    cur = None
    for r in res:
        if r["asset_class"] != cur:
            cur = r["asset_class"]; print("\n=== %s ===" % cur)
        if r["ok"]:
            print("  [OK  ] %-18s %s %6dms %8dB %s" % (r["name"], r["status"], r["ms"], r["bytes"], r["ctype"][:24]))
            print("         %s" % r["sample"][:135])
        else:
            print("  [FAIL] %-18s %s" % (r["name"], r.get("error","?")))
    print("\n" + "="*74)
    for ac in ["EQUITY","FX","CMDTY","BOND","CRYPTO","NEWS"]:
        ok = [r["name"] for r in res if r["asset_class"]==ac and r["ok"]]
        print("%-7s %d/%d  %s" % (ac, len(ok), len([r for r in res if r["asset_class"]==ac]), ", ".join(ok) or "*** NONE ***"))

if __name__ == "__main__":
    main()
