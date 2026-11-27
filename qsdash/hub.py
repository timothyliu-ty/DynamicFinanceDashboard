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

from . import alerts as alerts_mod
from . import config
from . import markets
from . import news as news_mod
from . import portfolio as portfolio_mod
from . import quant as quant_mod
from .storage import TimeSeriesStore

CLASSES = config.ASSET_CLASSES + ["NEWS"]


def _now():
    return datetime.now().astimezone()


def _fetch_class(cls):
    if cls == "NEWS":
        return news_mod.news()
    return markets.ADAPTERS[cls]()


class Hub(object):
    def __init__(self, db_path=None, alerts_path=None, portfolio_path=None):
        self._lock = threading.RLock()
        self._latest = {}      # cls -> 最近一次结果
        self._last_good = {}   # cls -> {"payload", "at": monotonic, "fetched_at": str}
        self._class_versions = {c: 0 for c in CLASSES}
        self._version = 0
        self._started_at = _now().isoformat(timespec="seconds")
        self._pool = ThreadPoolExecutor(max_workers=7)
        self._stop = threading.Event()
        self._thread = None

        # 量化组件：时序存储、加密衍生品、告警、模拟组合
        self.store = TimeSeriesStore(db_path=db_path)
        self.alerts = alerts_mod.AlertEngine(path=alerts_path)
        self.portfolio = portfolio_mod.PortfolioBook(path=portfolio_path)
        self._crypto_deriv = None
        self._curve_history = []
        self._quant_cache = None
        self._quant_dirty = True

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

            # 剥离庞大的 curve_history，避免每轮在 classes.BONDS 重复传输
            ch = result.pop("curve_history", None)
            if cls == "BONDS" and ch:
                self._curve_history = ch

            self._latest[cls] = result
            self._class_versions[cls] = self._class_versions.get(cls, 0) + 1
            self._version += 1
            self._quant_dirty = True

        # 异步/无阻断持久化与告警评估
        try:
            if result.get("ok") and cls != "NEWS":
                self.store.record_quotes(cls, result.get("quotes") or [])
            if cls == "BONDS" and ch:
                self.store.record_curve_history(ch)
        except Exception:
            pass

        try:
            q_snap = self.quant_snapshot()
            with self._lock:
                classes_copy = {c: self._latest.get(c) for c in CLASSES}
            self.alerts.evaluate(classes_copy, q_snap)
        except Exception:
            pass
        return result

    def refresh_crypto_derivatives(self):
        """刷新加密永续资金费率、基差、持仓量与跨所价差（独立于主报价，失败不拖垮 CRYPTO）。"""
        with self._lock:
            spot = ((self._latest.get("CRYPTO") or {}).get("quotes")) or []
        try:
            res = markets.crypto_derivatives(spot_quotes=spot)
        except Exception as e:
            res = {"ok": False, "rows": [], "source": "binance-fapi + okx",
                   "error": "internal: %s" % e}
        with self._lock:
            self._crypto_deriv = res
            self._version += 1
            self._quant_dirty = True
        try:
            if res.get("ok") and res.get("rows"):
                self.store.record_funding(res["rows"])
        except Exception:
            pass
        try:
            q_snap = self.quant_snapshot()
            with self._lock:
                classes_copy = {c: self._latest.get(c) for c in CLASSES}
            self.alerts.evaluate(classes_copy, q_snap)
        except Exception:
            pass
        return res

    def refresh_all(self, include_deriv=False):
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(self.refresh, CLASSES))
        if include_deriv:
            self.refresh_crypto_derivatives()

    def mark_dirty(self):
        with self._lock:
            self._quant_dirty = True
            self._version += 1

    # --------------------------------------------------------------- snapshot
    def quant_snapshot(self):
        with self._lock:
            if not self._quant_dirty and self._quant_cache is not None:
                return self._quant_cache
            classes = {c: self._latest.get(c) for c in CLASSES}
            deriv = self._crypto_deriv
            ch = self._curve_history
        q = quant_mod.build_quant_snapshot(
            classes, store=self.store, crypto_deriv=deriv, curve_history=ch or None
        )
        with self._lock:
            self._quant_cache = q
            self._quant_dirty = False
        return q

    def snapshot(self):
        q = self.quant_snapshot()
        with self._lock:
            classes = {c: self._latest.get(c) for c in CLASSES}
            version = self._version
            started_at = self._started_at
            class_versions = dict(self._class_versions)
        ok_n = sum(1 for c in CLASSES if (classes.get(c) or {}).get("ok"))
        return {
            "server_time": _now().isoformat(timespec="seconds"),
            "started_at": started_at,
            "version": version,
            "class_versions": class_versions,
            "classes": classes,
            "quant": q,
            "alerts": self.alerts.list_state(),
            "portfolio": self.portfolio.value(classes),
            "summary": {
                "classes_ok": ok_n,
                "classes_total": len(CLASSES),
                "degraded": [c for c in CLASSES if not (classes.get(c) or {}).get("ok")],
            },
        }

    def delta_since(self, seen_versions):
        """仅返回自 seen_versions 以来发生变化的资产类 + 轻量量化/告警/持仓状态（SSE 增量推送）。"""
        q = self.quant_snapshot()
        with self._lock:
            classes = {c: self._latest.get(c) for c in CLASSES}
            version = self._version
            class_versions = dict(self._class_versions)
        changed = {}
        for c in CLASSES:
            if class_versions.get(c, 0) != (seen_versions or {}).get(c, -1):
                changed[c] = classes.get(c)
        ok_n = sum(1 for c in CLASSES if (classes.get(c) or {}).get("ok"))
        return {
            "server_time": _now().isoformat(timespec="seconds"),
            "version": version,
            "class_versions": class_versions,
            "changed": changed,
            "quant": q,
            "alerts": self.alerts.list_state(),
            "portfolio": self.portfolio.value(classes),
            "summary": {
                "classes_ok": ok_n,
                "classes_total": len(CLASSES),
                "degraded": [c for c in CLASSES if not (classes.get(c) or {}).get("ok")],
            },
        }

    # ------------------------------------------------------------- scheduler
    def _loop(self):
        due = {c: 0.0 for c in CLASSES}
        due_deriv = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            for cls in CLASSES:
                if now >= due[cls]:
                    due[cls] = now + config.REFRESH.get(cls, 30)
                    self._pool.submit(self._safe_refresh, cls)
            if now >= due_deriv:
                due_deriv = now + config.CRYPTO_DERIV_REFRESH
                self._pool.submit(self.refresh_crypto_derivatives)
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
                self._class_versions[cls] = self._class_versions.get(cls, 0) + 1
                self._version += 1
                self._quant_dirty = True

    def start(self, prime=True):
        if prime:
            self.refresh_all(include_deriv=True)
        self._thread = threading.Thread(target=self._loop, name="qsdash-scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._pool.shutdown(wait=False)
        self.store.close()
