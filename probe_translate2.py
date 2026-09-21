#!/usr/bin/env python3
"""MyMemory 深挖：额度字段、自动语言识别、连续请求的限流行为、译文质量参照。"""
import json, ssl, time, urllib.parse, urllib.request

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}


def call(q, pair, timeout=20):
    url = "https://api.mymemory.translated.net/get?q=%s&langpair=%s" % (urllib.parse.quote(q), urllib.parse.quote(pair))
    t0 = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout, context=CTX) as r:
            return json.loads(r.read().decode("utf-8", "replace")), (time.time() - t0) * 1000, None
    except Exception as e:
        return None, (time.time() - t0) * 1000, "%s: %s" % (type(e).__name__, e)


print("== 1) 完整响应结构（找额度字段）==")
d, ms, err = call("Fed holds rates steady as inflation cools", "en|zh-CN")
if d:
    print("   %.0fms" % ms)
    for k in sorted(d.keys()):
        v = d[k]
        if k == "matches":
            print("   %-18s [%d 条，首条 score=%.2f]" % (k, len(v), v[0].get("score", 0) if v else -1))
        else:
            print("   %-18s %s" % (k, json.dumps(v, ensure_ascii=False)[:150]))
else:
    print("   FAIL", err)

print()
print("== 2) 自动语言识别（EN/中 混合，省去判断源语言）==")
for pair in ["Autodetect|zh-CN", "autodetect|zh-CN"]:
    d, ms, err = call("Nvidia shares jump after earnings beat", pair)
    got = (d or {}).get("responseData", {}).get("translatedText", err)
    print("   %-20s -> %s" % (pair, str(got)[:70]))

print()
print("== 3) 中 -> 英（双向验证）==")
for pair in ["zh-CN|en", "Autodetect|en"]:
    d, ms, err = call("美联储维持利率不变，通胀降温", pair)
    got = (d or {}).get("responseData", {}).get("translatedText", err)
    print("   %-20s -> %s" % (pair, str(got)[:70]))

print()
print("== 4) 连续 12 次请求：是否限流 / 额度耗尽的表现 ==")
heads = [
    "Oil climbs as OPEC signals deeper cuts",
    "Dollar steady ahead of payrolls report",
    "Gold hits record high on safe-haven demand",
    "Treasury yields slip after weak auction",
    "Apple unveils new AI features at event",
    "Tesla deliveries miss estimates",
    "China factory activity returns to growth",
    "ECB officials split on rate path",
    "Ethereum upgrade goes live on mainnet",
    "Japan stocks rally as yen weakens",
    "Retail sales beat expectations in August",
    "Bank earnings kick off reporting season",
]
ok = fail = 0
lat = []
for i, h in enumerate(heads, 1):
    d, ms, err = call(h, "en|zh-CN")
    lat.append(ms)
    if d and d.get("responseStatus") == 200:
        ok += 1
        txt = d["responseData"]["translatedText"]
        print("   #%-2d %5.0fms  %s" % (i, ms, txt[:52]))
    else:
        fail += 1
        detail = err or json.dumps(d.get("responseDetails", "") if d else "", ensure_ascii=False)[:60]
        print("   #%-2d %5.0fms  FAIL %s" % (i, ms, detail))
print("   -> 成功 %d / 失败 %d，延迟 min=%.0fms max=%.0fms avg=%.0fms"
      % (ok, fail, min(lat), max(lat), sum(lat) / len(lat)))

print()
print("== 5) 空/超长/特殊字符的边界 ==")
for q in ["", "A" * 480, "Stocks & bonds: what's next? <b>bold</b> 100%"]:
    d, ms, err = call(q, "en|zh-CN")
    st = (d or {}).get("responseStatus")
    txt = (d or {}).get("responseData", {}).get("translatedText", err)
    print("   len=%-4d status=%-4s -> %s" % (len(q), st, str(txt)[:60]))
