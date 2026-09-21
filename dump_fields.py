#!/usr/bin/env python3
"""字段序位实测：把每个端点的原始字段按索引打印出来，供 SPEC-DASH 做映射。
不猜索引——所有字段映射必须能在这里被肉眼核对。"""
import ssl, urllib.request
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
      "Referer": "https://finance.sina.com.cn"}

def get(url, hdrs=None, enc="gbk"):
    h = dict(UA); h.update(hdrs or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=15, context=CTX) as r:
        return r.read().decode(enc, "replace")

def dump(title, raw, sep=","):
    print("\n" + "="*78 + "\n### " + title)
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line: continue
        if "=" in line and line.startswith("var "):
            key, _, val = line.partition("=")
            val = val.strip().strip(";").strip('"')
            fs = val.split(sep)
            print("-- %s  (%d fields)" % (key.replace("var hq_str_", ""), len(fs)))
            for i, f in enumerate(fs):
                print("   [%2d] %s" % (i, f[:70]))
        else:
            print("   raw: %s" % line[:140])

dump("SINA  US EQUITY  gb_aapl", get("https://hq.sinajs.cn/list=gb_aapl"))
dump("SINA  GLOBAL INDEX  int_dji / int_sp500", get("https://hq.sinajs.cn/list=int_dji,int_sp500"))
dump("SINA  CN INDEX  sh000001", get("https://hq.sinajs.cn/list=sh000001"))
dump("SINA  FX  fx_susdcny / fx_seurusd", get("https://hq.sinajs.cn/list=fx_susdcny,fx_seurusd"))
dump("SINA  CMDTY(global)  hf_GC / hf_CL", get("https://hq.sinajs.cn/list=hf_GC,hf_CL"))
dump("SINA  CMDTY(domestic) nf_AU0", get("https://hq.sinajs.cn/list=nf_AU0"))
dump("TENCENT  US EQUITY  usAAPL", get("https://qt.gtimg.cn/q=usAAPL"))
dump("TENCENT  CMDTY  hf_GC", get("https://qt.gtimg.cn/q=hf_GC"))
