"""标准库 HTTP 服务 + 增量 SSE 推送（AC-D5）+ 量化数据/风控 API。无任何 Web 框架。

路由：
    GET  /                     静态终端页
    GET  /static/<file>        静态资源（含目录穿越防护）
    GET  /api/snapshot         全量快照 JSON（含 quant / alerts / portfolio）
    GET  /api/quant            量化分析快照 JSON（曲线/PCA/跨资产价差/衍生品/相关性/宏观状态）
    GET  /api/history          SQLite 时序查询（?symbol=BTC&asset_class=CRYPTO&limit=300 或 ?type=curve|funding）
    GET  /api/export.csv       导出时序数据 CSV（供外部 Python / Excel 研究）
    GET  /api/alerts           告警规则与触发历史
    POST /api/alerts           新增/更新告警规则或清空触发记录
    DELETE /api/alerts?id=...  删除告警规则
    GET  /api/portfolio        组合持仓与实时盯市 PnL / 敞口汇总
    POST /api/portfolio        新增/更新持仓
    DELETE /api/portfolio?id=  删除持仓
    GET  /api/watchlist        当前标的池与自定义扩展
    POST /api/watchlist        保存自定义自选扩展并触发刷新
    GET  /api/health           轻量健康检查
    GET  /api/stream           Server-Sent Events：首帧全量，后续增量 delta + 每 1s 心跳
    GET  /api/i18n             可用语言 + 翻译额度
    POST /api/translate        按需翻译新闻标题（AC-D8；浏览器不直连第三方）
"""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import config, i18n

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _safe_static_path(rel):
    """AC-D5.4 目录穿越防护：解析后必须仍在 STATIC_DIR 内。"""
    root = os.path.realpath(config.STATIC_DIR)
    target = os.path.realpath(os.path.join(root, rel.lstrip("/")))
    if target != root and not target.startswith(root + os.sep):
        return None
    if not os.path.isfile(target):
        return None
    return target


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "qsdash/2.0"

    hub = None

    def log_message(self, fmt, *args):   # 静音默认访问日志，保持终端干净
        pass

    # ------------------------------------------------------------------ utils
    def _send(self, code, body, ctype, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str),
                   MIME[".json"])

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            n = 0
        if n <= 0 or n > 256 * 1024:
            return None, "请求体缺失或过大"
        try:
            req = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            return None, "请求体不是合法 JSON: %s" % e
        if not isinstance(req, dict):
            return None, "请求体必须是对象"
        return req, None

    # -------------------------------------------------------------------- GET
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            return self._serve_static("index.html")
        if path == "/api/snapshot":
            return self._json(self.hub.snapshot())
        if path == "/api/quant":
            return self._json(self.hub.quant_snapshot())
        if path == "/api/history":
            return self._handle_history(qs)
        if path == "/api/export.csv":
            sym = (qs.get("symbol") or [None])[0]
            cls = (qs.get("asset_class") or [None])[0]
            limit = int((qs.get("limit") or ["5000"])[0] or 5000)
            csv_body = self.hub.store.export_csv(symbol=sym, asset_class=cls, limit=limit)
            fname = "qsdash_%s.csv" % (sym or cls or "all").lower()
            return self._send(200, csv_body, MIME[".csv"],
                              {"Content-Disposition": 'attachment; filename="%s"' % fname})
        if path == "/api/alerts":
            return self._json(self.hub.alerts.list_state())
        if path == "/api/portfolio":
            snap = self.hub.snapshot()
            return self._json(snap["portfolio"])
        if path == "/api/watchlist":
            return self._json({
                "overrides": config.load_watchlist(),
                "universe": config.get_universe(),
            })
        if path == "/api/health":
            snap = self.hub.snapshot()
            return self._json({"ok": True, "server_time": snap["server_time"],
                               "summary": snap["summary"]})
        if path == "/api/stream":
            return self._stream()
        if path == "/api/i18n":
            return self._json({"locales": sorted(i18n.TARGETS), "source": i18n.SOURCE,
                               "provider": i18n.PROVIDER, "max_batch": i18n.MAX_BATCH,
                               "budget": i18n.budget()})
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        if path.startswith("/static/"):
            return self._serve_static(path[len("/static/"):])
        return self._json({"error": "not found", "path": path}, 404)

    def _handle_history(self, qs):
        kind = ((qs.get("type") or ["ticks"])[0] or "ticks").lower()
        try:
            limit = int((qs.get("limit") or ["300"])[0] or 300)
        except ValueError:
            limit = 300
        if kind == "curve":
            rows = self.hub.store.get_curve_history(days=limit)
            return self._json({"ok": True, "type": "curve", "count": len(rows), "rows": rows})
        sym = ((qs.get("symbol") or [""])[0] or "").strip().upper()
        if not sym:
            return self._json({"ok": False, "error": "symbol parameter is required"}, 400)
        if kind == "funding":
            rows = self.hub.store.get_funding_history(sym, limit=limit)
            return self._json({"ok": True, "type": "funding", "symbol": sym,
                               "count": len(rows), "rows": rows})
        cls = ((qs.get("asset_class") or [None])[0] or None)
        since = ((qs.get("since") or [None])[0] or None)
        rows = self.hub.store.get_series(sym, asset_class=cls, limit=limit, since=since)
        return self._json({"ok": True, "type": "ticks", "symbol": sym, "asset_class": cls,
                           "count": len(rows), "rows": rows})

    # ------------------------------------------------------------------- POST
    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/translate":
            return self._handle_translate()
        if path == "/api/alerts":
            req, err = self._read_json()
            if err:
                return self._json({"ok": False, "error": err}, 400)
            if req.get("action") == "clear":
                self.hub.alerts.clear_triggered()
                self.hub.mark_dirty()
                return self._json({"ok": True, "alerts": self.hub.alerts.list_state()})
            try:
                rec = self.hub.alerts.add_rule(req)
            except ValueError as e:
                return self._json({"ok": False, "error": str(e)}, 400)
            self.hub.mark_dirty()
            return self._json({"ok": True, "rule": rec, "alerts": self.hub.alerts.list_state()})

        if path == "/api/portfolio":
            req, err = self._read_json()
            if err:
                return self._json({"ok": False, "error": err}, 400)
            try:
                rec = self.hub.portfolio.add_position(req)
            except ValueError as e:
                return self._json({"ok": False, "error": str(e)}, 400)
            self.hub.mark_dirty()
            snap = self.hub.snapshot()
            return self._json({"ok": True, "position": rec, "portfolio": snap["portfolio"]})

        if path == "/api/watchlist":
            req, err = self._read_json()
            if err:
                return self._json({"ok": False, "error": err}, 400)
            clean = {}
            for k in ("us_equity", "cn_equity", "crypto", "fx", "commodities"):
                v = req.get(k)
                if isinstance(v, list):
                    clean[k] = [str(x).strip() for x in v if str(x).strip()][:50]
            config.save_watchlist(clean)
            self.hub.mark_dirty()
            return self._json({"ok": True, "overrides": clean, "universe": config.get_universe()})

        return self._json({"error": "not found", "path": path}, 404)

    # ----------------------------------------------------------------- DELETE
    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        item_id = ((qs.get("id") or [""])[0] or "").strip()

        if path == "/api/alerts":
            if not item_id:
                return self._json({"ok": False, "error": "id is required"}, 400)
            deleted = self.hub.alerts.delete_rule(item_id)
            if deleted:
                self.hub.mark_dirty()
            return self._json({"ok": deleted, "alerts": self.hub.alerts.list_state()},
                              200 if deleted else 404)

        if path == "/api/portfolio":
            if not item_id:
                return self._json({"ok": False, "error": "id is required"}, 400)
            deleted = self.hub.portfolio.delete_position(item_id)
            if deleted:
                self.hub.mark_dirty()
            snap = self.hub.snapshot()
            return self._json({"ok": deleted, "portfolio": snap["portfolio"]},
                              200 if deleted else 404)

        return self._json({"error": "not found", "path": path}, 404)

    def _handle_translate(self):
        req, err = self._read_json()
        if err:
            return self._json({"ok": False, "error": err}, 400)
        to = (req.get("to") or "").strip()
        if to not in i18n.TARGETS:
            return self._json({"ok": False,
                               "error": "不支持的 to=%r，可用: %s"
                                        % (to, sorted(i18n.TARGETS))}, 400)
        texts = req.get("texts")
        if not isinstance(texts, list) or not texts:
            return self._json({"ok": False, "error": "texts 必须是非空数组"}, 400)
        texts = [t for t in texts if isinstance(t, str)][:i18n.MAX_BATCH]
        if not texts:
            return self._json({"ok": False, "error": "texts 内没有字符串"}, 400)

        results, bud = i18n.translate_many(texts, to)
        return self._json({"ok": True, "to": to, "provider": i18n.PROVIDER,
                           "count": len(results), "results": results, "budget": bud})

    def _serve_static(self, rel):
        fn = _safe_static_path(unquote(rel))
        if not fn:
            return self._json({"error": "static file not found", "path": rel}, 404)
        ctype = MIME.get(os.path.splitext(fn)[1].lower(), "application/octet-stream")
        try:
            with open(fn, "rb") as f:
                data = f.read()
        except OSError as e:
            return self._json({"error": "read failed: %s" % e}, 500)
        self._send(200, data, ctype)

    # ------------------------------------------------------------------- SSE
    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        last_version = -1
        seen_class_versions = None
        last_beat = 0.0
        try:
            while True:
                now = time.time()
                with self.hub._lock:
                    cur_ver = self.hub._version
                payload = None
                if cur_ver != last_version:
                    if seen_class_versions is None:
                        snap = self.hub.snapshot()
                        last_version = snap["version"]
                        seen_class_versions = dict(snap.get("class_versions") or {})
                        payload = {"type": "snapshot", "data": snap}
                    else:
                        delta = self.hub.delta_since(seen_class_versions)
                        last_version = delta["version"]
                        seen_class_versions = dict(delta.get("class_versions") or {})
                        payload = {"type": "delta", "data": delta}
                    last_beat = now
                elif now - last_beat >= 1.0:
                    snap = self.hub.snapshot()
                    payload = {"type": "heartbeat", "server_time": snap["server_time"],
                               "summary": snap["summary"]}
                    last_beat = now
                if payload is not None:
                    chunk = ("data: %s\n\n" % json.dumps(payload, ensure_ascii=False,
                                                           default=str)).encode("utf-8")
                    self.wfile.write(chunk)
                    self.wfile.flush()
                time.sleep(0.25)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


def make_server(hub, host="127.0.0.1", port=8848):
    Handler.hub = hub
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd
