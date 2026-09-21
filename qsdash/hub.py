"""聚合层：按类别分档刷新、保留最后有效值、线程安全快照（AC-D4）。

新鲜度语义（这是本系统不造假的核心）：
- 刷新成功 -> ok=True，quotes 为本次抓取结果
- 刷新失败 -> ok=False，quotes 仍为上一次有效值，但附 last_good_age_s
  UI 收到 ok=False 必须置灰 + 报错，不得把旧值当实时值渲染
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import config
from . import markets
from . import news as news_mod

CLASSES = config.ASSET_CLASSES + ["NEWS"]


def _now():
    return datetime.now().astimezone()


def _fetch_class(cls):
    if cls == "NEWS":
        return news_mod.news()
    return markets.ADAPTERS[cls]()


class Hub(object):
    def __init__(self):
        self._lock = threading.RLock()
        self._latest = {}      # cls -> 最近一次结果
        self._last_good = {}   # cls -> {"quotes"/"items", "at": monotonic, "fetched_at": str}
        self._version = 0
        self._started_at = _now().isoformat(timespec="seconds")
        self._pool = ThreadPoolExecutor(max_workers=6)
        self._stop = threading.Event()
        self._thread = None

    # ---------------------------------------------------------------- refresh
    def refresh(self, cls):
        result = _fetch_class(cls)
        now = time.monotonic()
        with self._lock:
            payload_key = "items" if cls == "NEWS" else "quotes"
            if result.get("ok") and result.get(payload_key):
                self._last_good[cls] = {
                    "payload": result[payload_key],
                    "at": now,
                    "fetched_at": result.get("fetched_at"),
                }
            lg = self._last_good.get(cls)
            if not result.get("ok") and lg:
                # 失败但仍有旧值：保留旧值，明确标注陈旧
                result = dict(result)
                result[payload_key] = lg["payload"]
                result["stale"] = True
                result["last_good_age_s"] = int(now - lg["at"])
                result["last_good_at"] = lg["fetched_at"]
            elif not result.get("ok"):
                result = dict(result)
                result["stale"] = True
                result["last_good_age_s"] = None
                result["last_good_at"] = None
            else:
                result = dict(result)
                result["stale"] = False
                result["last_good_age_s"] = 0
                result["last_good_at"] = result.get("fetched_at")
            result["last_refresh_ms"] = int(now * 1000)
            self._latest[cls] = result
            self._version += 1
        return result

    def refresh_all(self):
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(self.refresh, CLASSES))

    # --------------------------------------------------------------- snapshot
    def snapshot(self):
        with self._lock:
            classes = {c: self._latest.get(c) for c in CLASSES}
            version = self._version
            started_at = self._started_at
        ok_n = sum(1 for c in CLASSES if (classes.get(c) or {}).get("ok"))
        return {
            "server_time": _now().isoformat(timespec="seconds"),
            "started_at": started_at,
            "version": version,
            "classes": classes,
            "summary": {
                "classes_ok": ok_n,
                "classes_total": len(CLASSES),
                "degraded": [c for c in CLASSES if not (classes.get(c) or {}).get("ok")],
            },
        }

    # ------------------------------------------------------------- scheduler
    def _loop(self):
        due = {c: 0.0 for c in CLASSES}
        while not self._stop.is_set():
            now = time.monotonic()
            for cls in CLASSES:
                if now >= due[cls]:
                    due[cls] = now + config.REFRESH.get(cls, 30)
                    self._pool.submit(self._safe_refresh, cls)
            self._stop.wait(0.5)

    def _safe_refresh(self, cls):
        try:
            self.refresh(cls)
        except Exception as e:  # 单类异常不得拖垮调度
            with self._lock:
                self._latest[cls] = {
                    "asset_class": cls, "ok": False, "error": "internal: %s" % e,
                    "quotes": [], "items": [], "skipped": [], "stale": True,
                    "last_good_age_s": None, "fetched_at": None,
                }
                self._version += 1

    def start(self, prime=True):
        if prime:
            self.refresh_all()
        self._thread = threading.Thread(target=self._loop, name="qsdash-scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._pool.shutdown(wait=False)
