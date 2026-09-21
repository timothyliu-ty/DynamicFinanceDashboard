#!/usr/bin/env python3
"""GitHub topic 检索（噪声低于全文检索），补齐选型证据。"""
import json, os, ssl, time, urllib.request
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github+json"}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

QUERIES = ["topic:market-data", "topic:financial-data", "topic:news-api",
           "topic:rss-reader", "topic:economic-data"]

def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20, context=CTX) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"__error__": "%s: %s" % (type(e).__name__, str(e)[:80])}

res = []
for q in QUERIES:
    d = get("https://api.github.com/search/repositories?q=%s&sort=stars&order=desc&per_page=6"
            % urllib.request.quote(q))
    print("\n=== %s (total=%s) ===" % (q, d.get("total_count", d.get("__error__", "?"))))
    if "items" not in d:
        time.sleep(4); continue
    for it in d["items"]:
        print("  %-40s %7d* %6df %-12s %s | %s" % (
            it["full_name"], it["stargazers_count"], it["forks_count"], it.get("language"),
            (it.get("pushed_at") or "")[:10], (it.get("description") or "")[:62]))
        res.append({"q": q, "full_name": it["full_name"], "stars": it["stargazers_count"],
                    "forks": it["forks_count"], "lang": it.get("language"),
                    "pushed": (it.get("pushed_at") or "")[:10],
                    "desc": it.get("description") or ""})
    time.sleep(7)
p = os.path.join(DATA_DIR, "github_topics.json")
json.dump(res, open(p, "w"), indent=2, ensure_ascii=False)
print("\nsaved -> %s (%d rows)" % (p, len(res)))
