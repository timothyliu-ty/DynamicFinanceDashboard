#!/usr/bin/env python3
"""GitHub 流行度实测：为取数/新闻选型提供星数证据（api.github.com，无需 token）。"""
import json, os, ssl, time, urllib.request

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github+json"}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

REPOS = ["ranaroussi/yfinance","ccxt/ccxt","akfamily/akshare","OpenBB-finance/OpenBB",
         "kurtmckee/feedparser","codelucas/newspaper","adbar/trafilatura","pydata/pandas-datareader",
         "QuantConnect/Lean","microsoft/qlib","finnhub-io/finnhub-python",
         "tradingview/lightweight-charts","plotly/plotly.js","mrmrs/colors",
         "scheb/feedparser","gto76/python-cheatsheet"]
SEARCHES = [
    "financial data api in:name,description,readme stars:>500",
    "stock market real time data stars:>500",
    "financial news rss scraper stars:>300",
    "market data terminal dashboard stars:>300",
    "economic data treasury yields stars:>100",
]

def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20, context=CTX) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"__error__": "%s: %s" % (type(e).__name__, str(e)[:90])}

def main():
    out = {"repos": [], "searches": []}
    print("=== GitHub search (by stars) ===")
    for q in SEARCHES:
        d = get("https://api.github.com/search/repositories?q=%s&sort=stars&order=desc&per_page=5"
                % urllib.request.quote(q))
        if "__error__" in d or "items" not in d:
            print("  [FAIL] %s -> %s" % (q[:44], d.get("__error__", d.get("message","?"))))
            time.sleep(3); continue
        rows = [{"full_name": it["full_name"], "stars": it["stargazers_count"],
                 "forks": it["forks_count"], "lang": it.get("language"),
                 "pushed": (it.get("pushed_at") or "")[:10],
                 "desc": (it.get("description") or "")[:90]} for it in d["items"]]
        out["searches"].append({"q": q, "total": d["total_count"], "top": rows})
        print("\n  Q: %s   (total=%d)" % (q, d["total_count"]))
        for r in rows:
            print("    %-40s %7d* %6df %-12s %s" % (r["full_name"], r["stars"], r["forks"], r["lang"], r["pushed"]))
        time.sleep(7)
    print("\n=== named repos ===")
    for full in REPOS:
        d = get("https://api.github.com/repos/%s" % full)
        if "__error__" in d or "stargazers_count" not in d:
            print("  [FAIL] %-34s %s" % (full, d.get("__error__", d.get("message","?")))); continue
        rec = {"full_name": d["full_name"], "stars": d["stargazers_count"], "forks": d["forks_count"],
               "lang": d.get("language"), "pushed": (d.get("pushed_at") or "")[:10],
               "license": (d.get("license") or {}).get("spdx_id"), "desc": (d.get("description") or "")[:80]}
        out["repos"].append(rec)
        print("  %-34s %7d* %6df %-12s pushed=%s %s" % (full, rec["stars"], rec["forks"], rec["lang"], rec["pushed"], rec["license"]))
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR,"github_popularity.json"),"w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()
