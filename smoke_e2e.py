#!/usr/bin/env python3
"""端到端自测（SPEC-DASH §5）：真起服务、真打接口、真读 SSE。

覆盖：静态页、目录穿越防护、快照完整性、报价自洽性、溯源字段、SSE 推送。
退出码非 0 表示自测失败。
"""
import http.client, json, os, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8899
BASE = "http://127.0.0.1:%d" % PORT
results = []


def check(name, cond, detail=""):
    results.append((bool(cond), name, detail))
    print("  [%s] %-46s %s" % ("PASS" if cond else "FAIL", name, detail[:96]))
    return bool(cond)


def http_get(path, timeout=30):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "smoke"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:
        return None, str(e).encode()


def http_post(path, payload, timeout=30):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "smoke"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, str(e).encode()


def wait_ready(proc, deadline=90):
    t0 = time.time()
    while time.time() - t0 < deadline:
        if proc.poll() is not None:
            return False
        code, _ = http_get("/api/health", timeout=3)
        if code == 200:
            return True
        time.sleep(1)
    return False


def main():
    env = dict(os.environ)
    proc = subprocess.Popen([sys.executable, "-m", "qsdash", "serve", "--port", str(PORT)],
                            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    try:
        if not wait_ready(proc):
            print("server did not become ready"); return 1
        # 首次全量刷新的余量
        time.sleep(6)

        print("\n== 静态资源 ==")
        code, body = http_get("/")
        check("GET / -> 200", code == 200, "status=%s" % code)
        check("index contains QS-DASH", b"QS-DASH" in body)
        code, body = http_get("/static/terminal.css")
        check("GET /static/terminal.css -> 200", code == 200 and b"--amber" in body)
        code, body = http_get("/static/terminal.js")
        check("GET /static/terminal.js -> 200", code == 200 and b"EventSource" in body)

        print("\n== 目录穿越防护 (AC-D5.4) ==")
        for bad in ["/static/../qsdash/config.py", "/static/..%2fqsdash/config.py",
                    "/static/../../Stock/SPEC-STOCK.md"]:
            code, _ = http_get(bad)
            check("blocks %s" % bad, code in (404, 400), "status=%s" % code)

        print("\n== 快照完整性 (AC-D2/D4) ==")
        code, raw = http_get("/api/snapshot")
        check("GET /api/snapshot -> 200", code == 200)
        snap = json.loads(raw)
        classes = snap.get("classes", {})
        expect = ["EQUITY", "FX", "COMMODITIES", "BONDS", "CRYPTO", "NEWS"]
        check("all 6 classes present", set(classes) == set(expect), str(sorted(classes)))
        ok_n = snap["summary"]["classes_ok"]
        check("all 6 classes ok", ok_n == 6,
              "ok=%d degraded=%s" % (ok_n, snap["summary"]["degraded"]))

        print("\n== 每类资产明细 ==")
        for cls in expect:
            r = classes.get(cls, {})
            rows = r.get("items") if cls == "NEWS" else r.get("quotes")
            rows = rows or []
            check("%-11s n=%d source=%s" % (cls, len(rows), r.get("source")),
                  r.get("ok") and len(rows) > 0 and r.get("fetched_at"),
                  "latency=%sms" % r.get("latency_ms"))

        print("\n== 报价自洽性 (AC-D2.4) ==")
        bad = []
        total = 0
        for cls in ["EQUITY", "FX", "COMMODITIES", "CRYPTO", "BONDS"]:
            for q in (classes.get(cls, {}).get("quotes") or []):
                if q.get("last") is None or q.get("prev_close") in (None, 0):
                    continue
                if q.get("change_pct") is None:
                    continue
                total += 1
                calc = (q["last"] - q["prev_close"]) / q["prev_close"] * 100
                if abs(calc - q["change_pct"]) > 0.03:
                    bad.append((cls, q["symbol"], calc, q["change_pct"]))
        check("all %d quotes self-consistent" % total, not bad, str(bad[:4]))

        print("\n== 缺少伪造值 (不造假铁律) ==")
        zeros = []
        for cls in expect:
            key = "items" if cls == "NEWS" else "quotes"
            for q in (classes.get(cls, {}).get(key) or []):
                if cls != "NEWS" and q.get("last") == 0 and q.get("currency") != "%":
                    zeros.append((cls, q.get("symbol")))
        check("no fabricated zero prices", not zeros, str(zeros[:5]))

        print("\n== 新闻 (AC-D3) ==")
        nr = classes.get("NEWS", {})
        items = nr.get("items") or []
        check("news items > 0", len(items) > 0, "n=%d" % len(items))
        check("news titles/links 100%%", all(i.get("title") and i.get("link") for i in items))
        ts_n = sum(1 for i in items if i.get("ts"))
        dated = sum(1 for i in items if i.get("ts_raw"))
        check("every item carrying a pubDate parsed", ts_n == dated,
              "parsed=%d dated=%d total=%d" % (ts_n, dated, len(items)))
        assumed = sum(1 for i in items if i.get("tz_assumed"))
        check("assumed-timezone items are flagged, not hidden",
              all(i.get("tz_assumed") is not None for i in items),
              "%d/%d tz_assumed" % (assumed, len(items)))
        feeds = nr.get("feeds") or []
        okf = sum(1 for f in feeds if f.get("ok"))
        check("all %d feeds ok" % len(feeds), okf == len(feeds), "%d/%d" % (okf, len(feeds)))
        sorted_ok = all((items[i].get("ts") or "") >= (items[i + 1].get("ts") or "")
                        for i in range(len(items) - 1))
        check("news sorted desc", sorted_ok)

        print("\n== SSE 推送 (AC-D5.3) ==")
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
        conn.request("GET", "/api/stream")
        resp = conn.getresponse()
        check("stream content-type", "text/event-stream" in resp.getheader("Content-Type", ""),
              resp.getheader("Content-Type"))
        buf = b""
        deadline = time.time() + 15
        while time.time() < deadline and buf.count(b"\n\n") < 2:
            try:
                chunk = resp.read1(4096)
            except Exception:
                break
            if not chunk:
                break
            buf += chunk
        events = [e for e in buf.decode("utf-8", "replace").split("\n\n") if e.strip()]
        check("received >=2 SSE events", len(events) >= 2, "events=%d" % len(events))
        kinds = set()
        for e in events:
            if e.startswith("data: "):
                try:
                    kinds.add(json.loads(e[6:]).get("type"))
                except Exception:
                    pass
        check("SSE event types valid", kinds <= {"snapshot", "heartbeat"} and kinds,
              str(sorted(kinds)))
        conn.close()

        print("\n== 国际化 / 翻译 (AC-D8) ==")
        code, raw = http_get("/api/i18n")
        check("GET /api/i18n -> 200", code == 200, "status=%s" % code)
        i18 = json.loads(raw) if code == 200 else {}
        check("locales en+zh advertised", set(i18.get("locales", [])) == {"en", "zh"},
              str(i18.get("locales")))
        bud = i18.get("budget") or {}
        check("daily quota explicit, not unbounded",
              bud.get("limit") == 5000 and "used" in bud and "remaining" in bud,
              "limit=%s used=%s remaining=%s"
              % (bud.get("limit"), bud.get("used"), bud.get("remaining")))

        code, body = http_get("/")
        check("shell carries language toggle", b'id="lang-tog"' in body)
        code, body = http_get("/static/terminal.js")
        check("client has i18n dictionary + MT badge",
              b"I18N" in body and b"mt-badge" in body)
        check("client translates lazily via /api/translate", b"/api/translate" in body)

        # 用真实新闻标题做端到端翻译（消耗真实额度，只取 3 条）
        real = [i["title"] for i in (classes.get("NEWS", {}).get("items") or [])[:3]
                if i.get("title")]
        check("have real headlines to translate", len(real) == 3, "n=%d" % len(real))
        if real:
            code, raw = http_post("/api/translate", {"to": "zh", "texts": real})
            check("POST /api/translate -> 200", code == 200, "status=%s" % code)
            d = json.loads(raw) if code == 200 else {}
            res = d.get("results") or []
            check("one result per requested text", len(res) == len(real),
                  "%d/%d" % (len(res), len(real)))
            check("every translation non-empty",
                  all(r.get("ok") and r.get("text") for r in res),
                  "ok=%d/%d" % (sum(1 for r in res if r.get("ok")), len(res)))
            han = sum(1 for r in res
                      if any("\u4e00" <= ch <= "\u9fff" for ch in (r.get("text") or "")))
            check("translations really contain Chinese", han == len(res),
                  "%d/%d" % (han, len(res)))
            b2 = d.get("budget") or {}
            check("budget accounted the requested chars",
                  b2.get("used", 0) >= sum(len(x) for x in real),
                  "used=%s chars for %d headlines" % (b2.get("used"), len(real)))

            code, raw = http_post("/api/translate", {"to": "zh", "texts": real})
            d3 = json.loads(raw) if code == 200 else {}
            check("repeat is cached, no extra quota spent",
                  (d3.get("budget") or {}).get("used") == b2.get("used"),
                  "used %s -> %s" % (b2.get("used"), (d3.get("budget") or {}).get("used")))
            check("cached results flagged cached",
                  all(r.get("cached") for r in (d3.get("results") or [])))

        code, _ = http_post("/api/translate", {"to": "fr", "texts": ["x"]})
        check("bad target rejected 400", code == 400, "status=%s" % code)
        code, _ = http_post("/api/translate", {"to": "zh", "texts": []})
        check("empty texts rejected 400", code == 400, "status=%s" % code)
        code, _ = http_post("/api/nope", {"x": 1})
        check("unknown POST route -> 404", code == 404, "status=%s" % code)

        print("\n== 运行日志 ==")
        proc.terminate()
        try:
            out = proc.communicate(timeout=8)[0].decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            proc.kill(); out = ""
        print("  " + out.strip().replace("\n", "\n  ")[:600])

    finally:
        if proc.poll() is None:
            proc.kill()

    passed = sum(1 for ok, _, _ in results if ok)
    print("\n" + "=" * 78)
    print("E2E: %d/%d passed" % (passed, len(results)))
    for ok, name, detail in results:
        if not ok:
            print("  FAILED: %s  %s" % (name, detail))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
