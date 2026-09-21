#!/usr/bin/env python3
"""抓取真实样本落盘为离线 fixture，使解析测试不依赖网络。
重新生成: python3 capture_fixtures.py     （样本会随行情变化，但结构不变）"""
import os, re, ssl, urllib.request

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "fixtures")
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
      "Referer": "https://finance.sina.com.cn"}

def get(url, enc="utf-8", headers=None):
    h = dict(UA); h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=25, context=CTX) as r:
        return r.read().decode(enc, "replace")

def save(name, text):
    p = os.path.join(FIX, name)
    with open(p, "w") as f:
        f.write(text)
    print("  %-28s %7d B" % (name, len(text)))

def trim_entries(xml, tag, n=3):
    """保留 feed 头 + 前 n 个 entry，得到结构相同但体积很小的 fixture。"""
    m = re.search(r"<entry", xml)
    if not m:
        return xml
    head = xml[:m.start()]
    entries = re.findall(r"<entry.*?</entry>", xml, re.S)[:n]
    return head + "".join(entries) + "</feed>"

def trim_rss(xml, n=5):
    m = re.search(r"<item", xml)
    if not m:
        return xml
    head = xml[:m.start()]
    items = re.findall(r"<item.*?</item>", xml, re.S)[:n]
    return head + "".join(items) + "</channel></rss>"

def main():
    os.makedirs(FIX, exist_ok=True)
    print("capturing fixtures -> %s" % FIX)
    S = "https://hq.sinajs.cn/list="
    save("sina_us.txt",   get(S + "gb_aapl,gb_msft,gb_nvda", "gbk"))
    save("sina_int.txt",  get(S + "int_dji,int_sp500,int_nikkei", "gbk"))
    save("sina_cn.txt",   get(S + "sh000001", "gbk"))
    save("sina_fx.txt",   get(S + "fx_susdcny,fx_seurusd", "gbk"))
    save("sina_hf.txt",   get(S + "hf_GC,hf_CL", "gbk"))
    save("treasury_nominal.xml",
         trim_entries(get("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
                          "?data=daily_treasury_yield_curve&field_tdr_date_value=2026"), "entry", 3))
    save("treasury_real.xml",
         trim_entries(get("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
                          "?data=daily_treasury_real_yield_curve&field_tdr_date_value=2026"), "entry", 3))
    save("binance_24hr.json",
         get("https://api.binance.com/api/v3/ticker/24hr?symbols=%5B%22BTCUSDT%22%2C%22ETHUSDT%22%5D"))
    save("rss_cnbc.xml",  trim_rss(get("https://www.cnbc.com/id/100003114/device/rss/rss.html"), 5))
    save("rss_google.xml", trim_rss(get("https://news.google.com/rss/search?q=stock+market+when:1d&hl=en-US&gl=US&ceid=US:en"), 5))
    print("done")

if __name__ == "__main__":
    main()
