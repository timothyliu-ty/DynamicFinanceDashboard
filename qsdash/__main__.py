"""qsdash 命令行（AC-D7）。

    python3 -m qsdash serve [--host H] [--port P] [--no-prime]
    python3 -m qsdash check                      # 一次性打全部源，失败则退出码非 0
    python3 -m qsdash snapshot [--json]          # 打印一次全量快照
"""

from __future__ import annotations

import argparse
import errno
import json
import sys

from . import config
from .hub import Hub, CLASSES


def _fmt(v, w=10, p=2):
    if v is None:
        return "—".rjust(w)
    try:
        return ("%.*f" % (p, float(v))).rjust(w)
    except (TypeError, ValueError):
        return str(v).rjust(w)


def cmd_check(args):
    hub = Hub()
    hub.refresh_all()
    snap = hub.snapshot()
    print("qsdash source check  %s" % snap["server_time"])
    print("=" * 78)
    failed = 0
    for cls in CLASSES:
        r = snap["classes"].get(cls) or {}
        ok = r.get("ok")
        n = len(r.get("items") or r.get("quotes") or [])
        mark = "OK  " if ok else "FAIL"
        if not ok:
            failed += 1
        print("[%s] %-12s n=%-4d src=%-12s latency=%-7s status=%s"
              % (mark, cls, n, r.get("source") or "-",
                 (str(r.get("latency_ms")) + "ms") if r.get("latency_ms") is not None else "-",
                 r.get("status")))
        if r.get("error"):
            print("        error: %s" % r["error"])
        for s in (r.get("skipped") or [])[:6]:
            print("        skipped: %s -> %s" % (s.get("symbol"), s.get("reason")))
        if cls == "NEWS":
            feeds = r.get("feeds") or []
            bad = [f for f in feeds if not f.get("ok")]
            print("        feeds ok=%d/%d%s" % (len(feeds) - len(bad), len(feeds),
                  ("  failed: " + ", ".join(f["feed"] for f in bad)) if bad else ""))
        elif cls != "NEWS":
            qs = r.get("quotes") or []
            for q in qs[:3]:
                print("        %-10s %-22s %s  %s%%"
                      % (q.get("symbol"), (q.get("name") or "")[:22],
                         _fmt(q.get("last")), _fmt(q.get("change_pct"), 8, 3)))
    print("=" * 78)
    print("classes ok=%d/%d  failed=%d" % (snap["summary"]["classes_ok"],
                                           snap["summary"]["classes_total"], failed))
    return 1 if failed else 0


def cmd_snapshot(args):
    hub = Hub()
    hub.refresh_all()
    snap = hub.snapshot()
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2, default=str))
        return 0
    print("qsdash snapshot  %s" % snap["server_time"])
    for cls in CLASSES:
        r = snap["classes"].get(cls) or {}
        rows = r.get("items") or r.get("quotes") or []
        print("\n== %s  (%s)  n=%d  %s" % (cls, r.get("source"), len(rows),
                                            "OK" if r.get("ok") else "FAIL: %s" % r.get("error")))
        for q in rows:
            if cls == "NEWS":
                print("   %-19s %s" % (q.get("ts") or "—", (q.get("title") or "")[:74]))
            else:
                print("   %-10s %-24s last=%-13s prev=%-13s chg=%-9s pct=%-9s %s"
                      % (q.get("symbol"), (q.get("name") or "")[:24],
                         _fmt(q.get("last"), 13, 4), _fmt(q.get("prev_close"), 13, 4),
                         _fmt(q.get("change"), 9, 4), _fmt(q.get("change_pct"), 9, 4),
                         q.get("quote_time") or ""))
    return 0


def cmd_serve(args):
    from .server import make_server
    hub = Hub()

    # 先绑端口再抓数据：端口被占时立刻失败，不让人白等一次全量刷新后才看到 traceback
    try:
        httpd = make_server(hub, args.host, args.port)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            print("端口 %d 已被占用（可能已经有一个 qsdash 在跑）" % args.port)
            print("  换端口：  python3 -m qsdash serve --port 9000")
            print("  看占用：  lsof -nP -iTCP:%d -sTCP:LISTEN" % args.port)
        else:
            print("无法绑定 %s:%d -> %s" % (args.host, args.port, e))
        return 2

    if not args.no_prime:
        print("priming all sources ...")
        hub.refresh_all()
        snap = hub.snapshot()
        print("primed: %d/%d classes ok %s" % (
            snap["summary"]["classes_ok"], snap["summary"]["classes_total"],
            ("(degraded: %s)" % ", ".join(snap["summary"]["degraded"]))
            if snap["summary"]["degraded"] else ""))
    hub.start(prime=False)
    print("qsdash terminal -> http://127.0.0.1:%d   (或 http://localhost:%d)"
          % (args.port, args.port))
    print("listening on %s   (--host 0.0.0.0 可对外，无鉴权)" % args.host)
    print("refreshing: " + ", ".join("%s=%ds" % (k, v) for k, v in config.REFRESH.items()))
    print("Ctrl-C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping ...")
    finally:
        hub.stop()
        httpd.server_close()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="qsdash", description="全球多资产实时终端")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("serve", help="启动终端")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8848)
    s.add_argument("--no-prime", action="store_true", help="启动时不预抓取")
    s.set_defaults(func=cmd_serve)

    c = sub.add_parser("check", help="一次性检查所有数据源")
    c.set_defaults(func=cmd_check)

    k = sub.add_parser("snapshot", help="打印一次快照")
    k.add_argument("--json", action="store_true")
    k.set_defaults(func=cmd_snapshot)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
