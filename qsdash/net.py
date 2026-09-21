"""标准库 HTTP 取数层：重试、显式编码、溯源记录（AC-D1）。

设计要点：
- 失败**不抛异常**，用 ok=False + error 表达，避免一个源拖垮整轮刷新
- 只对网络层异常重试；HTTP 4xx/5xx 立即返回（重试端点否决是噪音）
- 每次调用都带 fetched_at 与 latency_ms，UI 页脚据此显示来源新鲜度
"""

from __future__ import annotations

import gzip
import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime

from . import config

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def fetch(url, headers=None, encoding="utf-8", timeout=None, retries=None):
    """取一次 HTTP。返回 dict，永不抛异常给调用方。"""
    timeout = config.HTTP_TIMEOUT if timeout is None else timeout
    retries = config.HTTP_RETRIES if retries is None else retries
    hdrs = {
        "User-Agent": config.USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, identity",
    }
    hdrs.update(headers or {})

    last_err = None
    attempts = retries + 1
    for attempt in range(attempts):
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
                raw = r.read()
                if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                    try:
                        raw = gzip.decompress(raw)
                    except OSError:
                        pass
                try:
                    body = raw.decode(encoding, "replace")
                except LookupError:
                    body = raw.decode("utf-8", "replace")
                return {
                    "ok": True, "status": r.status, "body": body, "bytes": len(raw),
                    "latency_ms": int((time.time() - t0) * 1000), "attempt": attempt + 1,
                    "fetched_at": _now_iso(), "endpoint": url, "error": None,
                    "encoding": encoding,
                }
        except urllib.error.HTTPError as e:
            # 端点否决：不重试
            return {
                "ok": False, "status": e.code, "body": "", "bytes": 0,
                "latency_ms": int((time.time() - t0) * 1000), "attempt": attempt + 1,
                "fetched_at": _now_iso(), "endpoint": url,
                "error": "HTTP %s %s" % (e.code, e.reason), "encoding": encoding,
            }
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError,
                ssl.SSLError, OSError) as e:
            last_err = "%s: %s" % (type(e).__name__, str(e)[:160])
            if attempt < attempts - 1:
                time.sleep(0.4 * (attempt + 1))
                continue
        except Exception as e:  # 兜底：绝不向上抛
            last_err = "%s: %s" % (type(e).__name__, str(e)[:160])

    return {
        "ok": False, "status": None, "body": "", "bytes": 0,
        "latency_ms": None, "attempt": attempts, "fetched_at": _now_iso(),
        "endpoint": url, "error": last_err or "unknown error", "encoding": encoding,
    }
