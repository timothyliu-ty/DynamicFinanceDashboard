"""SQLite 时间序列存储与查询引擎。

记录轮询快照、美债 YTD 每日曲线、永续资金费率与跨所价差，为量化统计、
滚动波动率、相关性矩阵及外部 Python 研究脚本（/api/history, /api/export.csv）提供真实历史数据。

铁律：
- 仅记录真实抓取到的非空数值，绝不插值或填 0
- 支持内存库（":memory:"）与自定义路径，测试完全隔离
"""

from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone

from . import config


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TimeSeriesStore(object):
    """线程安全的轻量 SQLite 时序存储。"""

    def __init__(self, db_path=None, min_write_interval_s=30.0):
        self.db_path = db_path if db_path is not None else config.DB_PATH
        self._min_interval = float(min_write_interval_s)
        self._lock = threading.RLock()
        self._last_written = {}  # (asset_class, symbol) -> (last_px, monotonic_ts)
        if self.db_path != ":memory:":
            parent = os.path.dirname(self.db_path)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            cur = self._conn.cursor()
            if self.db_path != ":memory:":
                cur.execute("PRAGMA journal_mode=WAL;")
                cur.execute("PRAGMA synchronous=NORMAL;")
            cur.executescript("""
                CREATE TABLE IF NOT EXISTS ticks (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_utc      TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    symbol      TEXT NOT NULL,
                    last        REAL NOT NULL,
                    prev_close  REAL,
                    change_pct  REAL,
                    high        REAL,
                    low         REAL,
                    volume      REAL,
                    extra_json  TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_ticks_cls_sym_ts
                    ON ticks (asset_class, symbol, ts_utc);
                CREATE INDEX IF NOT EXISTS idx_ticks_sym_ts
                    ON ticks (symbol, ts_utc);

                CREATE TABLE IF NOT EXISTS curve_daily (
                    as_of     TEXT NOT NULL,
                    tenor     TEXT NOT NULL,
                    yield_pct REAL NOT NULL,
                    is_real   INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (as_of, tenor, is_real)
                );

                CREATE TABLE IF NOT EXISTS funding_ticks (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_utc         TEXT NOT NULL,
                    symbol         TEXT NOT NULL,
                    mark_price     REAL,
                    index_price    REAL,
                    funding_rate   REAL,
                    basis_bps      REAL,
                    oi_usd         REAL,
                    dispersion_bps REAL
                );
                CREATE INDEX IF NOT EXISTS idx_funding_sym_ts
                    ON funding_ticks (symbol, ts_utc);
            """)
            self._conn.commit()

    def close(self):
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # ----------------------------------------------------------------- writes
    def record_quotes(self, asset_class, quotes, ts_utc=None, force=False):
        """写入一轮报价。仅当价格变化或超过最小间隔时落盘，避免重复噪音。"""
        if not quotes:
            return 0
        ts = ts_utc or _utc_now()
        now_m = time.monotonic()
        rows = []
        with self._lock:
            for q in quotes:
                sym = q.get("symbol")
                last = q.get("last")
                if not sym or last is None:
                    continue
                try:
                    last_f = float(last)
                except (TypeError, ValueError):
                    continue
                key = (asset_class, sym)
                prev = self._last_written.get(key)
                if not force and prev is not None:
                    prev_px, prev_t = prev
                    if prev_px == last_f and (now_m - prev_t) < self._min_interval:
                        continue
                self._last_written[key] = (last_f, now_m)
                extra = q.get("extra")
                rows.append((
                    ts, asset_class, sym, last_f,
                    q.get("prev_close"), q.get("change_pct"),
                    q.get("high"), q.get("low"), q.get("volume"),
                    json.dumps(extra, ensure_ascii=False, separators=(",", ":")) if extra else None,
                ))
            if not rows:
                return 0
            self._conn.executemany(
                "INSERT INTO ticks (ts_utc, asset_class, symbol, last, prev_close, "
                "change_pct, high, low, volume, extra_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
            return len(rows)

    def record_curve_history(self, curve_history):
        """持久化美债名义与 TIPS 日频曲线历史（幂等 UPSERT）。"""
        if not curve_history:
            return 0
        rows = []
        for entry in curve_history:
            dt = entry.get("as_of")
            if not dt:
                continue
            for tenor, val in (entry.get("nominal") or {}).items():
                if val is not None:
                    rows.append((dt, tenor, float(val), 0))
            for tenor, val in (entry.get("real") or {}).items():
                if val is not None:
                    rows.append((dt, tenor, float(val), 1))
        if not rows:
            return 0
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO curve_daily (as_of, tenor, yield_pct, is_real) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
            return len(rows)

    def record_funding(self, deriv_rows, ts_utc=None):
        """写入加密永续资金费率、基差、持仓量与跨所价差快照。"""
        if not deriv_rows:
            return 0
        ts = ts_utc or _utc_now()
        rows = []
        for d in deriv_rows:
            sym = d.get("symbol")
            if not sym:
                continue
            rows.append((
                ts, sym, d.get("mark_price"), d.get("index_price"),
                d.get("funding_rate"), d.get("basis_bps"),
                d.get("oi_usd"), d.get("dispersion_bps"),
            ))
        if not rows:
            return 0
        with self._lock:
            self._conn.executemany(
                "INSERT INTO funding_ticks (ts_utc, symbol, mark_price, index_price, "
                "funding_rate, basis_bps, oi_usd, dispersion_bps) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
            return len(rows)

    # ---------------------------------------------------------------- queries
    def get_series(self, symbol, asset_class=None, limit=500, since=None):
        """按时间正序返回单个标的的历史点。"""
        sql = ("SELECT ts_utc, asset_class, symbol, last, prev_close, change_pct, "
               "high, low, volume FROM ticks WHERE symbol = ?")
        params = [symbol.upper()]
        if asset_class:
            sql += " AND asset_class = ?"
            params.append(asset_class.upper())
        if since:
            sql += " AND ts_utc >= ?"
            params.append(since)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 10000)))
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
        rows.reverse()
        return rows

    def get_recent_prices_by_class(self, limit_per_symbol=60):
        """批量取出各 (asset_class, symbol) 最近 N 条价格用于计算 Z-score/波动率/sparkline。"""
        sql = """
            SELECT asset_class, symbol, ts_utc, last
            FROM (
                SELECT asset_class, symbol, ts_utc, last, id,
                       ROW_NUMBER() OVER (PARTITION BY asset_class, symbol ORDER BY id DESC) AS rn
                FROM ticks
            )
            WHERE rn <= ?
            ORDER BY asset_class, symbol, id ASC
        """
        out = {}
        with self._lock:
            cur = self._conn.execute(sql, (int(limit_per_symbol),))
            for r in cur.fetchall():
                key = (r["asset_class"], r["symbol"])
                out.setdefault(key, []).append((r["ts_utc"], float(r["last"])))
        return out

    def get_curve_history(self, days=180):
        """按日期正序返回最近 N 个交易日的美债名义/实际曲线。"""
        with self._lock:
            cur = self._conn.execute(
                "SELECT DISTINCT as_of FROM curve_daily ORDER BY as_of DESC LIMIT ?",
                (int(days),),
            )
            dates = [r["as_of"] for r in cur.fetchall()]
            if not dates:
                return []
            dates.reverse()
            placeholders = ",".join("?" for _ in dates)
            cur = self._conn.execute(
                "SELECT as_of, tenor, yield_pct, is_real FROM curve_daily "
                "WHERE as_of IN (%s) ORDER BY as_of ASC" % placeholders,
                dates,
            )
            by_date = {d: {"as_of": d, "nominal": {}, "real": {}} for d in dates}
            for r in cur.fetchall():
                bucket = "real" if r["is_real"] else "nominal"
                by_date[r["as_of"]][bucket][r["tenor"]] = float(r["yield_pct"])
            return [by_date[d] for d in dates]

    def get_funding_history(self, symbol, limit=200):
        with self._lock:
            cur = self._conn.execute(
                "SELECT ts_utc, symbol, mark_price, index_price, funding_rate, "
                "basis_bps, oi_usd, dispersion_bps FROM funding_ticks "
                "WHERE symbol = ? ORDER BY id DESC LIMIT ?",
                (symbol.upper(), max(1, min(int(limit), 5000))),
            )
            rows = [dict(r) for r in cur.fetchall()]
        rows.reverse()
        return rows

    def export_csv(self, symbol=None, asset_class=None, limit=5000):
        """导出 RFC 4180 CSV 供外部研究脚本/Excel 使用。"""
        sql = ("SELECT ts_utc, asset_class, symbol, last, prev_close, change_pct, "
               "high, low, volume FROM ticks WHERE 1=1")
        params = []
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol.upper())
        if asset_class:
            sql += " AND asset_class = ?"
            params.append(asset_class.upper())
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 50000)))
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
        rows = list(reversed(rows))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ts_utc", "asset_class", "symbol", "last", "prev_close",
                    "change_pct", "high", "low", "volume"])
        for r in rows:
            w.writerow([r["ts_utc"], r["asset_class"], r["symbol"], r["last"],
                        r["prev_close"], r["change_pct"], r["high"], r["low"], r["volume"]])
        return buf.getvalue()

    def stats(self):
        with self._lock:
            ticks_n = self._conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
            syms_n = self._conn.execute("SELECT COUNT(DISTINCT symbol) FROM ticks").fetchone()[0]
            curve_days = self._conn.execute("SELECT COUNT(DISTINCT as_of) FROM curve_daily").fetchone()[0]
            funding_n = self._conn.execute("SELECT COUNT(*) FROM funding_ticks").fetchone()[0]
            rng = self._conn.execute("SELECT MIN(ts_utc), MAX(ts_utc) FROM ticks").fetchone()
        size_bytes = 0
        if self.db_path != ":memory:" and os.path.isfile(self.db_path):
            try:
                size_bytes = os.path.getsize(self.db_path)
            except OSError:
                pass
        return {
            "db_path": self.db_path,
            "ticks": ticks_n,
            "symbols": syms_n,
            "curve_days": curve_days,
            "funding_ticks": funding_n,
            "first_ts": rng[0] if rng else None,
            "last_ts": rng[1] if rng else None,
            "size_bytes": size_bytes,
        }
