"""标准库 HTTP 服务 + SSE 推送（AC-D5）。无任何 Web 框架。

路由：
    GET /                静态终端页
    GET /static/<file>   静态资源（含目录穿越防护）
    GET /api/snapshot    全量快照 JSON
    GET /api/health      轻量健康检查
    GET /api/stream      Server-Sent Events：快照变化即推，另每 1s 心跳
    GET /api/i18n        可用语言 + 翻译额度
    POST /api/translate  按需翻译新闻标题（AC-D8；浏览器不直连第三方）
"""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from . import config, i18n

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
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
    server_version = "qsdash/1.0"

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

    # -------------------------------------------------------------------- GET
    def do_GET(self):
        path = urlparse(self.path).path

        if path in ("/", "/index.html"):
            return self._serve_static("index.html")
        if path == "/api/snapshot":
            return self._json(self.hub.snapshot())
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

    # ------------------------------------------------------------------- POST
    def do_POST(self):
        """仅 `/api/translate`：按需翻译，绝不批量预翻（AC-D8.3/D8.4）。"""
        path = urlparse(self.path).path
        if path != "/api/translate":
            return self._json({"error": "not found", "path": path}, 404)

        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            n = 0
        if n <= 0 or n > 256 * 1024:
            return self._json({"ok": False, "error": "请求体缺失或过大"}, 400)
        try:
            req = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            return self._json({"ok": False, "error": "请求体不是合法 JSON: %s" % e}, 400)
        if not isinstance(req, dict):
            return self._json({"ok": False, "error": "请求体必须是对象"}, 400)

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
        last_beat = 0.0
        try:
            while True:
                snap = self.hub.snapshot()
                now = time.time()
                payload = None
                if snap["version"] != last_version:
                    last_version = snap["version"]
                    payload = {"type": "snapshot", "data": snap}
                    last_beat = now
                elif now - last_beat >= 1.0:
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
