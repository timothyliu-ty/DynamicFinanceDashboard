"""组合持仓与实时盯市风控（Portfolio / MTM PnL & Exposure Overlay）。

原则：
- 仅管理本地模拟/盯市持仓（绝不接券商、绝不下单）
- 严守不造假铁律：标的无实时价格时，市值与盈亏为 None 并标注 unpriced，绝不填 0
- 计算：多/空/总/净敞口、分资产类别敞口、集中度 HHI、单日 PnL 与未实现 PnL
"""

from __future__ import annotations

import json
import os
import threading
import uuid

from . import config

VALID_SIDES = ("LONG", "SHORT")


class PortfolioBook(object):
    def __init__(self, path=None):
        self.path = path if path is not None else config.PORTFOLIO_PATH
        self._lock = threading.RLock()
        self._positions = []
        self._load()

    def _load(self):
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("positions"), list):
                    self._positions = data["positions"]
                    return
            except (OSError, ValueError):
                pass
            self._positions = []

    def _save(self):
        try:
            parent = os.path.dirname(self.path)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"positions": self._positions}, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def list_positions(self):
        with self._lock:
            return [dict(p) for p in self._positions]

    def add_position(self, pos):
        if not isinstance(pos, dict):
            raise ValueError("position must be a JSON object")
        sym = str(pos.get("symbol") or "").strip().upper()
        if not sym:
            raise ValueError("symbol is required")
        side = str(pos.get("side") or "LONG").strip().upper()
        if side not in VALID_SIDES:
            raise ValueError("side must be LONG or SHORT")
        try:
            qty = float(pos["qty"])
            entry = float(pos["entry_price"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("qty and entry_price must be numbers")
        if qty <= 0 or entry <= 0:
            raise ValueError("qty and entry_price must be positive")

        rec = {
            "id": (pos.get("id") or ("pos-" + uuid.uuid4().hex[:8])),
            "symbol": sym,
            "asset_class": (str(pos.get("asset_class") or "").strip().upper() or None),
            "side": side,
            "qty": qty,
            "entry_price": entry,
            "note": str(pos.get("note") or "").strip()[:120],
        }
        with self._lock:
            self._positions = [p for p in self._positions if p["id"] != rec["id"]]
            self._positions.append(rec)
            self._save()
        return rec

    def delete_position(self, pos_id):
        with self._lock:
            before = len(self._positions)
            self._positions = [p for p in self._positions if p.get("id") != pos_id]
            changed = len(self._positions) != before
            if changed:
                self._save()
            return changed

    def value(self, classes):
        """按当前行情快照对所有持仓实时盯市，返回明细与风险汇总。"""
        by_pair = {}
        by_sym = {}
        for cls, payload in (classes or {}).items():
            if cls == "NEWS" or not payload:
                continue
            for q in (payload.get("quotes") or []):
                sym = q.get("symbol")
                if not sym:
                    continue
                by_pair[(cls, sym)] = (cls, q)
                by_sym.setdefault(sym, (cls, q))

        positions = self.list_positions()
        rows = []
        long_notional = 0.0
        short_notional = 0.0
        total_upnl = 0.0
        total_day_pnl = 0.0
        priced_n = 0
        unpriced_n = 0
        by_class = {}

        for p in positions:
            cls_hint = p.get("asset_class")
            hit = by_pair.get((cls_hint, p["symbol"])) if cls_hint else None
            if not hit:
                hit = by_sym.get(p["symbol"])
            matched_cls = hit[0] if hit else (cls_hint or "UNKNOWN")
            q = hit[1] if hit else None
            mark = q.get("last") if q else None
            chg = q.get("change") if q else None
            sign = 1.0 if p["side"] == "LONG" else -1.0

            if mark is None:
                unpriced_n += 1
                rows.append(dict(
                    p, asset_class=matched_cls, priced=False,
                    mark_price=None, notional=None, signed_notional=None,
                    unrealized_pnl=None, unrealized_pnl_pct=None, day_pnl=None,
                ))
                continue

            priced_n += 1
            notional = abs(p["qty"] * mark)
            signed_notional = sign * notional
            upnl = sign * (mark - p["entry_price"]) * p["qty"]
            upnl_pct = sign * (mark - p["entry_price"]) / p["entry_price"] * 100.0
            day_pnl = (sign * chg * p["qty"]) if chg is not None else None

            if sign > 0:
                long_notional += notional
            else:
                short_notional += notional
            total_upnl += upnl
            if day_pnl is not None:
                total_day_pnl += day_pnl

            bc = by_class.setdefault(matched_cls, {"gross": 0.0, "net": 0.0, "pnl": 0.0, "count": 0})
            bc["gross"] += notional
            bc["net"] += signed_notional
            bc["pnl"] += upnl
            bc["count"] += 1

            rows.append(dict(
                p, asset_class=matched_cls, priced=True,
                mark_price=round(mark, 6),
                notional=round(notional, 2),
                signed_notional=round(signed_notional, 2),
                unrealized_pnl=round(upnl, 2),
                unrealized_pnl_pct=round(upnl_pct, 2),
                day_pnl=round(day_pnl, 2) if day_pnl is not None else None,
            ))

        gross = long_notional + short_notional
        net = long_notional - short_notional
        # 权重与集中度 HHI（Herfindahl-Hirschman Index，0~1）
        hhi = 0.0
        for r in rows:
            if r["priced"] and gross > 0:
                w = r["notional"] / gross
                r["weight_pct"] = round(w * 100.0, 2)
                hhi += w * w
            else:
                r["weight_pct"] = None

        exposure_by_class = {
            k: {
                "gross": round(v["gross"], 2),
                "net": round(v["net"], 2),
                "pnl": round(v["pnl"], 2),
                "weight_pct": round(v["gross"] / gross * 100.0, 2) if gross > 0 else 0.0,
                "count": v["count"],
            }
            for k, v in by_class.items()
        }

        return {
            "positions": rows,
            "summary": {
                "count": len(rows),
                "priced": priced_n,
                "unpriced": unpriced_n,
                "gross_exposure": round(gross, 2),
                "net_exposure": round(net, 2),
                "long_notional": round(long_notional, 2),
                "short_notional": round(short_notional, 2),
                "unrealized_pnl": round(total_upnl, 2) if priced_n else None,
                "day_pnl": round(total_day_pnl, 2) if priced_n else None,
                "concentration_hhi": round(hhi, 4) if priced_n else None,
            },
            "exposure_by_class": exposure_by_class,
        }
