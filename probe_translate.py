#!/usr/bin/env python3
"""翻译端点可行性探针：无鉴权、标准库可用的候选逐个实测。

判据：能返回像样译文 + 可批量 + 延迟可接受。测不通的明确记为不可用，不猜。
"""
import json, ssl, time, urllib.parse, urllib.request

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}

SAMPLES = [
    "Fed holds rates steady as inflation cools",
    "Nvidia shares jump after earnings beat",
    "Bitcoin slips below $82,000 as ETF outflows accelerate",
]


def get(url, headers=None, timeout=15):
    h = dict(UA); h.update(headers or {})
    t0 = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout, context=CTX) as r:
            body = r.read().decode("utf-8", "replace")
        return r.status, body, (time.time() - t0) * 1000
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e), (time.time() - t0) * 1000


def post(url, data, headers=None, timeout=20):
    h = dict(UA); h.update(headers or {})
    h.setdefault("Content-Type", "application/json")
    body = json.dumps(data).encode("utf-8")
    t0 = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=h), timeout=timeout, context=CTX) as r:
            return r.status, r.read().decode("utf-8", "replace"), (time.time() - t0) * 1000
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e), (time.time() - t0) * 1000


def show(name, status, body, ms):
    ok = status == 200
    print("  [%s] %-34s %6.0fms  %s" % (" OK " if ok else "FAIL", name, ms, body[:150].replace("\n", " ") if body else ""))


print("=" * 100)
print("A) Google 非官方 translate_a/single (client=gtx)  —— 单条")
u = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q="
     + urllib.parse.quote(SAMPLES[0]))
show("google gtx single", *get(u))

print("\nB) 同一端点 —— 批量：重复 q 参数")
u = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t"
     + "".join("&q=" + urllib.parse.quote(s) for s in SAMPLES))
st, body, ms = get(u)
show("google gtx multi-q", st, body, ms)
if st == 200:
    try:
        d = json.loads(body)
        n = len([x for x in d[0] if x and x[0]])
        print("         -> 返回 %d 段（送了 %d 条）%s" % (n, len(SAMPLES), "批量可用" if n >= len(SAMPLES) else "批量不可用，只翻了第一条"))
    except Exception as e:
        print("         -> 解析失败:", e)

print("\nC) MyMemory（匿名，有额度限制）")
u = "https://api.mymemory.translated.net/get?q=" + urllib.parse.quote(SAMPLES[0]) + "&langpair=en|zh-CN"
st, body, ms = get(u)
show("mymemory", st, body, ms)
if st == 200:
    try:
        d = json.loads(body)
        print("         -> %s | quota=%s" % (d.get("responseData", {}).get("translatedText", "")[:80],
                                             d.get("responseDetails", "")[:80]))
    except Exception as e:
        print("         -> 解析失败:", e)

print("\nD) LibreTranslate 公共实例（多数已要求 key）")
for host in ["https://libretranslate.com", "https://translate.terraprint.co", "https://lt.vern.cc"]:
    show(host, *post(host + "/translate", {"q": SAMPLES[0], "source": "en", "target": "zh", "format": "text"}))

print("\nE) 反向：中 -> 英（验证双向）")
u = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=zh-CN&tl=en&dt=t&q="
     + urllib.parse.quote("美联储维持利率不变，通胀降温"))
show("google gtx zh->en", *get(u))

print("\nF) auto 源语言探测（中英混合场景）")
for s in ["美联储维持利率不变", "Fed holds rates steady"]:
    u = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-CN&dt=t&q="
         + urllib.parse.quote(s))
    st, body, ms = get(u)
    show("auto->zh: " + s[:18], st, body[:110] if st == 200 else body, ms)

print("\nG) 稳定性：同一请求连打 5 次（看是否限流）")
fails = 0
for i in range(5):
    st, body, ms = get("https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q="
                       + urllib.parse.quote(SAMPLES[i % 3]))
    if st != 200:
        fails += 1
    print("     #%d status=%s  %.0fms" % (i + 1, st, ms))
print("     -> 失败 %d/5" % fails)
