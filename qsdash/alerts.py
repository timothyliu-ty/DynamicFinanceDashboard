"""规则驱动的量化告警引擎。

支持规则类型：
- price_above / price_below      标的价格阈值（如 BTC > 100000、10Y > 5.0）
- pct_move_abs                   涨跌幅绝对值（如任意标的或指定标的 >= 3%）
- spread_above / spread_below    跨资产价差阈值（如 2S10S < 0 倒挂、CNH_CNY > 200 pips）
- zscore_abs                     统计 Z-Score 异动（|z| >= 2.0）
- funding_ann_abs                加密永续年化资金费率极端值（|funding_ann_pct| >= 30%）
- dispersion_bps                 跨所现货价差套利机会（|dispersion_bps| >= 15 bps）
- news_keyword                   新闻标题关键词匹配（如 FOMC、emergency）

每条规则带冷却时间（cooldown_s），避免重复刷屏；支持可选异步 webhook 推送。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
import uuid
from datetime import datetime

from . import config

RULE_TYPES = {
    "price_above", "price_below", "pct_move_abs",
    "spread_above", "spread_below", "zscore_abs",
    "funding_ann_abs", "dispersion_bps", "news_keyword",
}

DEFAULT_RULES = [
    {"id": "def-2s10s-inv", "name": "UST 2s10s Yield Curve Inversion",
     "type": "spread_below", "target": "2S10S", "threshold": 0.0,
     "cooldown_s": 3600, "enabled": True},
    {"id": "def-cnh-stress", "name": "CNH-CNY Offshore Stress (>200 pips)",
     "type": "spread_above", "target": "CNH_CNY", "threshold": 200.0,
     "cooldown_s": 900, "enabled": True},
    {"id": "def-btc-move", "name": "BTC 24h Move >= 5%",
     "type": "pct_move_abs", "target": "BTC", "threshold": 5.0,
     "cooldown_s": 600, "enabled": True},
    {"id": "def-funding-hi", "name": "Perp Annualized Funding >= 30%",
     "type": "funding_ann_abs", "target": "*", "threshold": 30.0,
     "cooldown_s": 900, "enabled": True},
    {"id": "def-disp-arb", "name": "Crypto Cross-Venue Dispersion >= 15 bps",
     "type": "dispersion_bps", "target": "*", "threshold": 15.0,
     "cooldown_s": 300, "enabled": True},
    {"id": "def-zscore", "name": "Statistical Anomaly (|Z| >= 2.5)",
     "type": "zscore_abs", "target": "*", "threshold": 2.5,
     "cooldown_s": 600, "enabled": True},
]


def _now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class AlertEngine(object):
    def __init__(self, path=None):
        self.path = path if path is not None else config.ALERTS_PATH
        self._lock = threading.RLock()
        self._rules = []
        self._triggered = []   # 最近触发记录（最多保留 100 条）
        self._cooldown = {}    # (rule_id, entity_key) -> monotonic_ts
        self._seen_news = set()
        self._load()

    def _load(self):
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("rules"), list):
                    self._rules = data["rules"]
                    self._triggered = (data.get("triggered") or [])[-100:]
                    return
            except (OSError, ValueError):
                pass
            self._rules = [dict(r) for r in DEFAULT_RULES]

    def _save(self):
        try:
            parent = os.path.dirname(self.path)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"rules": self._rules, "triggered": self._triggered[-100:]},
                          f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def list_state(self):
        with self._lock:
            return {
                "rules": [dict(r) for r in self._rules],
                "triggered": list(reversed(self._triggered[-50:])),
                "active_rules": sum(1 for r in self._rules if r.get("enabled", True)),
                "triggered_count": len(self._triggered),
            }

    def add_rule(self, rule):
        if not isinstance(rule, dict):
            raise ValueError("rule must be a JSON object")
        rtype = (rule.get("type") or "").strip()
        if rtype not in RULE_TYPES:
            raise ValueError("unsupported rule type: %r (valid: %s)" % (rtype, sorted(RULE_TYPES)))
        target = str(rule.get("target") or "*").strip()
        if rtype != "news_keyword":
            target = target.upper()
            try:
                threshold = float(rule["threshold"])
            except (KeyError, TypeError, ValueError):
                raise ValueError("threshold must be a number")
        else:
            threshold = None
            if not target or target == "*":
                raise ValueError("news_keyword requires a non-empty keyword target")

        rec = {
            "id": (rule.get("id") or ("al-" + uuid.uuid4().hex[:8])),
            "name": (rule.get("name") or ("%s %s %s" % (target, rtype, threshold))).strip()[:120],
            "type": rtype,
            "target": target,
            "threshold": threshold,
            "cooldown_s": max(10, int(rule.get("cooldown_s") or 300)),
            "enabled": bool(rule.get("enabled", True)),
            "webhook_url": (rule.get("webhook_url") or "").strip() or None,
        }
        with self._lock:
            self._rules = [r for r in self._rules if r["id"] != rec["id"]]
            self._rules.append(rec)
            self._save()
        return rec

    def delete_rule(self, rule_id):
        with self._lock:
            before = len(self._rules)
            self._rules = [r for r in self._rules if r.get("id") != rule_id]
            changed = len(self._rules) != before
            if changed:
                self._save()
            return changed

    def clear_triggered(self):
        with self._lock:
            self._triggered = []
            self._save()

    def _fire(self, rule, entity, value, message):
        now_m = time.monotonic()
        ckey = (rule["id"], entity)
        cd = float(rule.get("cooldown_s") or 300)
        if ckey in self._cooldown and (now_m - self._cooldown[ckey]) < cd:
            return None
        self._cooldown[ckey] = now_m
        ev = {
            "id": "ev-" + uuid.uuid4().hex[:8],
            "rule_id": rule["id"],
            "rule_name": rule.get("name"),
            "type": rule["type"],
            "target": entity,
            "value": value,
            "threshold": rule.get("threshold"),
            "message": message,
            "ts": _now_iso(),
        }
        self._triggered.append(ev)
        if len(self._triggered) > 100:
            self._triggered = self._triggered[-100:]
        wh = rule.get("webhook_url")
        if wh and (wh.startswith("http://") or wh.startswith("https://")):
            threading.Thread(target=_post_webhook, args=(wh, ev), daemon=True).start()
        return ev

    def evaluate(self, classes, quant_snap=None):
        """在最新行情与量化快照上评估所有启用的规则，返回本轮新触发的事件列表。"""
        fired = []
        # 索引所有行情报价
        quotes = []
        for cls, payload in (classes or {}).items():
            if cls == "NEWS" or not payload or not payload.get("ok"):
                continue
            for q in (payload.get("quotes") or []):
                quotes.append((cls, q))

        spreads_by = {s["id"]: s for s in ((quant_snap or {}).get("spreads") or [])}
        sym_stats = (quant_snap or {}).get("symbol_stats") or {}
        deriv_rows = ((quant_snap or {}).get("crypto_deriv") or {}).get("rows") or []
        news_items = ((classes or {}).get("NEWS") or {}).get("items") or []

        with self._lock:
            for rule in self._rules:
                if not rule.get("enabled", True):
                    continue
                rt = rule["type"]
                tgt = rule.get("target") or "*"
                thr = rule.get("threshold")

                if rt in ("price_above", "price_below"):
                    for _, q in quotes:
                        sym = q.get("symbol")
                        last = q.get("last")
                        if last is None or (tgt != "*" and sym != tgt):
                            continue
                        hit = (last > thr) if rt == "price_above" else (last < thr)
                        if hit:
                            ev = self._fire(rule, sym, last,
                                            "%s last=%s %s %s" % (sym, last, ">" if rt == "price_above" else "<", thr))
                            if ev:
                                fired.append(ev)

                elif rt == "pct_move_abs":
                    for _, q in quotes:
                        sym = q.get("symbol")
                        pct = q.get("change_pct")
                        if pct is None or (tgt != "*" and sym != tgt):
                            continue
                        if abs(pct) >= thr:
                            ev = self._fire(rule, sym, pct,
                                            "%s move %+.2f%% (>= %.2f%%)" % (sym, pct, thr))
                            if ev:
                                fired.append(ev)

                elif rt in ("spread_above", "spread_below"):
                    sp = spreads_by.get(tgt)
                    if sp and sp.get("value") is not None:
                        val = float(sp["value"])
                        hit = (val > thr) if rt == "spread_above" else (val < thr)
                        if hit:
                            ev = self._fire(rule, tgt, val,
                                            "%s = %s %s (%s %s)" % (
                                                sp["name"], val, sp.get("unit") or "",
                                                ">" if rt == "spread_above" else "<", thr))
                            if ev:
                                fired.append(ev)

                elif rt == "zscore_abs":
                    for key, st in sym_stats.items():
                        z = st.get("zscore")
                        sym = st.get("symbol")
                        if z is None or (tgt != "*" and sym != tgt):
                            continue
                        if abs(z) >= thr:
                            ev = self._fire(rule, sym, z,
                                            "%s z-score=%+.2f (n=%d, |z|>=%.2f)" % (sym, z, st.get("n", 0), thr))
                            if ev:
                                fired.append(ev)

                elif rt == "funding_ann_abs":
                    for row in deriv_rows:
                        sym = row.get("symbol")
                        ann = row.get("funding_ann_pct")
                        if ann is None or (tgt != "*" and sym != tgt):
                            continue
                        if abs(ann) >= thr:
                            ev = self._fire(rule, sym, ann,
                                            "%s perp funding %+.2f%%/yr (basis=%s bp)" % (
                                                sym, ann, row.get("basis_bps")))
                            if ev:
                                fired.append(ev)

                elif rt == "dispersion_bps":
                    for row in deriv_rows:
                        sym = row.get("symbol")
                        disp = row.get("dispersion_bps")
                        if disp is None or (tgt != "*" and sym != tgt):
                            continue
                        if abs(disp) >= thr:
                            ev = self._fire(rule, sym, disp,
                                            "%s OKX-Binance spread %+.1f bps" % (sym, disp))
                            if ev:
                                fired.append(ev)

                elif rt == "news_keyword":
                    rx = re.compile(re.escape(tgt), re.I)
                    for it in news_items[:40]:
                        title = it.get("title") or ""
                        nkey = (rule["id"], it.get("link") or title)
                        if nkey in self._seen_news:
                            continue
                        if rx.search(title):
                            self._seen_news.add(nkey)
                            ev = self._fire(rule, tgt, it.get("source"),
                                            "[NEWS] %s (%s)" % (title[:90], it.get("source") or ""))
                            if ev:
                                fired.append(ev)

            if fired:
                self._save()
        return fired


def _post_webhook(url, payload):
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "qsdash-alert/2.0"})
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        pass
