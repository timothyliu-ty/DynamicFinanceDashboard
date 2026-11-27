"""五类资产适配器（AC-D2）。

字段索引逐位对应 SPEC-DASH §2.2 的实证表，不得出现该表之外的索引。
所有适配器返回同一形状：
    {asset_class, ok, quotes[], skipped[], error, source, endpoint, fetched_at, latency_ms, as_of}
失败时 ok=False 且 quotes 为空 —— 由 hub 保留「最后已知有效值」，此处绝不填 0 冒充。
"""

from __future__ import annotations

import json
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import config
from . import net

SINA_HEADERS = {"Referer": "https://finance.sina.com.cn"}


def _num(v):
    """宽松数值解析：空串/非数返回 None。不返回 0 —— 0 是有效行情，不能当缺失。"""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _env(asset_class, source, endpoint, ok, quotes, skipped=None,
         error=None, status=None, fetched_at=None, latency_ms=None, as_of=None, **extra_fields):
    out = {
        "asset_class": asset_class,
        "ok": bool(ok) and len(quotes) > 0,
        "quotes": quotes,
        "skipped": skipped or [],
        "error": error if not (ok and quotes) else None,
        "source": source,
        "endpoint": endpoint,
        "status": status,
        "fetched_at": fetched_at,
        "latency_ms": latency_ms,
        "as_of": as_of,
    }
    out.update(extra_fields)
    return out


def _parse_sina(body):
    """解析 var hq_str_xxx="a,b,c"; 形式的换行载荷。"""
    out = {}
    for line in (body or "").strip().split("\n"):
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().replace("var hq_str_", "").strip()
        if not key:
            continue
        out[key] = val.strip().rstrip(";").strip('"').split(",")
    return out


def _quote(symbol, name, last, prev, chg, pct, **kw):
    """统一报价。AC-D2.4：涨跌幅与计算值冲突超 0.02pp 时以计算值为准并打标。"""
    extra = dict(kw.pop("extra", None) or {})
    if last is not None and prev not in (None, 0):
        calc = (last - prev) / prev * 100.0
        if pct is None:
            pct = round(calc, 4)
        elif abs(calc - pct) > 0.02:
            extra["pct_conflict"] = True
            extra["pct_reported"] = pct
            pct = round(calc, 4)
        if chg is None:
            chg = round(last - prev, 6)
    high = kw.get("high")
    low = kw.get("low")
    if (high is not None and low is not None and prev not in (None, 0)
            and high >= low and "range_pct" not in extra):
        extra["range_pct"] = round((high - low) / abs(prev) * 100.0, 4)
    q = {"symbol": symbol, "name": name, "last": last, "prev_close": prev,
         "change": chg, "change_pct": pct}
    q.update(kw)
    if extra:
        q["extra"] = extra
    return q


# ------------------------------------------------------------------ EQUITIES
def equities():
    """三组 sina 前缀，三种布局（SPEC-DASH §2.2a/b/c）。"""
    u = config.get_universe()["EQUITY"]
    groups = [("us", "gb_", "US Equity", "US"),
              ("int_idx", "", "Global Index", "GLOBAL"),
              ("cn_idx", "", "China Index", "CN")]
    quotes, skipped, endpoints, lats, errs = [], [], [], [], []
    fetched = None
    status = None

    for key, prefix, group, venue in groups:
        syms = u[key]
        url = config.SINA_QUOTE + ",".join(prefix + s for s in syms)
        res = net.fetch(url, headers=SINA_HEADERS, encoding="gbk")
        endpoints.append(url)
        if res.get("latency_ms") is not None:
            lats.append(res["latency_ms"])
        fetched = res.get("fetched_at") or fetched
        if status is None:
            status = res.get("status")
        if not res["ok"]:
            errs.append("%s: %s" % (group, res.get("error")))
            skipped.append({"symbol": group, "reason": res.get("error")})
            continue

        rows = _parse_sina(res["body"])
        for s in syms:
            f = rows.get(prefix + s)
            if not f:
                skipped.append({"symbol": prefix + s, "reason": "端点未返回该标的"})
                continue
            try:
                if group == "US Equity":
                    last_v = _num(f[1])
                    h52 = _num(f[8])
                    l52 = _num(f[9])
                    vol = _num(f[10])
                    extra = {"h52": h52, "l52": l52,
                             "mktcap": _num(f[12]), "pe": _num(f[14])}
                    if last_v is not None and h52 and l52 and h52 > l52 > 0:
                        extra["pos_52w"] = round((last_v - l52) / (h52 - l52) * 100.0, 2)
                    if last_v is not None and h52 and h52 > 0:
                        extra["dd_52w"] = round((last_v - h52) / h52 * 100.0, 2)
                    if last_v is not None and vol is not None and vol > 0:
                        extra["dollar_vol"] = round(last_v * vol, 2)
                    quotes.append(_quote(
                        s.upper(), f[0], last_v, _num(f[26]), _num(f[4]), _num(f[2]),
                        open=_num(f[5]), high=_num(f[6]), low=_num(f[7]), volume=vol,
                        currency="USD", quote_time=(f[3] or None), group=group, venue=venue,
                        extra=extra))
                elif group == "Global Index":
                    last, chg, pct = _num(f[1]), _num(f[2]), _num(f[3])
                    prev = (last - chg) if (last is not None and chg is not None) else None
                    quotes.append(_quote(
                        s.replace("int_", "").upper(), f[0], last, prev, chg, pct,
                        open=None, high=None, low=None, volume=None, currency="",
                        quote_time=None, group=group, venue=venue))
                else:
                    quotes.append(_quote(
                        s.upper(), f[0], _num(f[3]), _num(f[2]), None, None,
                        open=_num(f[1]), high=_num(f[4]), low=_num(f[5]), volume=_num(f[8]),
                        currency="", quote_time=(f[31] or None), group=group, venue=venue))
            except (IndexError, TypeError) as e:
                skipped.append({"symbol": prefix + s, "reason": "字段不足: %s" % e})

    return _env("EQUITY", "sina", " | ".join(endpoints), bool(quotes), quotes, skipped,
                error="; ".join(errs) if errs else None, status=status,
                fetched_at=fetched, latency_ms=max(lats) if lats else None)


# ------------------------------------------------------------------------ FX
def fx():
    """AC-D2.5：只取实证过的 [8]最新 [3]昨收 [10]涨跌幅 [11]涨跌额 [0]时间 [9]名称 [17]日期。
    买卖价 [5][6] 未获互证，不输出。"""
    syms = config.get_universe()["FX"]
    url = config.SINA_QUOTE + ",".join(syms)
    res = net.fetch(url, headers=SINA_HEADERS, encoding="gbk")
    quotes, skipped = [], []
    if res["ok"]:
        rows = _parse_sina(res["body"])
        for s in syms:
            f = rows.get(s)
            if not f or len(f) < 12:
                skipped.append({"symbol": s, "reason": "字段不足或缺失"})
                continue
            try:
                quotes.append(_quote(
                    s.replace("fx_s", "").upper(), f[9], _num(f[8]), _num(f[3]),
                    _num(f[11]), _num(f[10]),
                    open=None, high=None, low=None, volume=None, currency="",
                    quote_time=(f[0] or None), group="FX Spot", venue="OTC",
                    extra={"date": f[17] if len(f) > 17 else None}))
            except (IndexError, TypeError) as e:
                skipped.append({"symbol": s, "reason": "字段不足: %s" % e})
    return _env("FX", "sina", url, res["ok"], quotes, skipped, error=res.get("error"),
                status=res.get("status"), fetched_at=res.get("fetched_at"),
                latency_ms=res.get("latency_ms"))


# --------------------------------------------------------------- COMMODITIES
def commodities():
    """只用国际盘 hf_*（AC-D2.6）。[0]最新 [2]买 [3]卖 [4]高 [5]低 [6]时间 [7]昨结 [8]开盘 [13]名称"""
    syms = config.get_universe()["COMMODITIES"]
    url = config.SINA_QUOTE + ",".join(syms)
    res = net.fetch(url, headers=SINA_HEADERS, encoding="gbk")
    quotes, skipped = [], []
    if res["ok"]:
        rows = _parse_sina(res["body"])
        for s in syms:
            f = rows.get(s)
            if not f or len(f) < 14:
                skipped.append({"symbol": s, "reason": "字段不足或缺失"})
                continue
            try:
                bid = _num(f[2])
                ask = _num(f[3])
                extra = {"bid": bid, "ask": ask,
                         "date": f[12] if len(f) > 12 else None}
                if bid is not None and ask is not None and ask >= bid > 0:
                    mid = (bid + ask) / 2.0
                    extra["spread_bps"] = round((ask - bid) / mid * 10000.0, 2)
                quotes.append(_quote(
                    s.replace("hf_", "").upper(), f[13] or s, _num(f[0]), _num(f[7]),
                    None, None, open=_num(f[8]), high=_num(f[4]), low=_num(f[5]),
                    volume=None, currency="USD", quote_time=(f[6] or None),
                    group="Futures (Global)", extra=extra))
            except (IndexError, TypeError) as e:
                skipped.append({"symbol": s, "reason": "字段不足: %s" % e})
    return _env("COMMODITIES", "sina", url, res["ok"], quotes, skipped, error=res.get("error"),
                status=res.get("status"), fetched_at=res.get("fetched_at"),
                latency_ms=res.get("latency_ms"))


# --------------------------------------------------------------------- BONDS
def _parse_treasury(body):
    root = ET.fromstring(body)
    rows = []
    for entry in root.iter():
        if not entry.tag.endswith("entry"):
            continue
        rec = {}
        for p in entry.iter():
            tag = p.tag.split("}")[-1]
            if tag == "NEW_DATE" or tag.startswith("BC_") or tag.startswith("TC_"):
                rec[tag] = (p.text or "").strip()
        if rec:
            rows.append(rec)
    rows.sort(key=lambda r: r.get("NEW_DATE", ""))
    return rows


def _build_curve_history(nom_rows, real_rows):
    """提取 YTD 美债名义/实际日频曲线历史（真实 XML 条目，无插值）。"""
    real_by_date = {}
    for r in real_rows or []:
        dt = (r.get("NEW_DATE") or "")[:10]
        if not dt:
            continue
        real_by_date[dt] = {
            tenor: _num(r.get(fld))
            for tenor, fld in config.TREASURY_REAL_FIELD.items()
            if _num(r.get(fld)) is not None
        }
    hist = []
    for r in nom_rows or []:
        dt = (r.get("NEW_DATE") or "")[:10]
        if not dt:
            continue
        nom = {}
        for tenor, fld in config.TREASURY_TENOR_FIELD.items():
            v = _num(r.get(fld))
            if v is not None:
                nom[tenor] = v
        if not nom:
            continue
        entry = {"as_of": dt, "nominal": nom}
        if dt in real_by_date and real_by_date[dt]:
            entry["real"] = real_by_date[dt]
        hist.append(entry)
    return hist


def bonds():
    """美债收益率曲线（日频，AC-D2.7）。含名义/TIPS 曲线、盈亏平衡通胀、蝶式利差及 YTD 历史。"""
    year = datetime.now().year
    url_n = config.TREASURY_NOMINAL.format(year=year)
    url_r = config.TREASURY_REAL.format(year=year)
    rn = net.fetch(url_n)
    rr = net.fetch(url_r)

    quotes, skipped = [], []
    as_of = None
    nom_rows, real_rows = [], []
    if rn["ok"]:
        try:
            nom_rows = _parse_treasury(rn["body"])
            if nom_rows:
                last = nom_rows[-1]
                prev = nom_rows[-2] if len(nom_rows) > 1 else None
                as_of = (last.get("NEW_DATE") or "")[:10]
                for tenor in config.UNIVERSE["BONDS"]:
                    y = _num(last.get(config.TREASURY_TENOR_FIELD[tenor]))
                    if y is None:
                        skipped.append({"symbol": tenor, "reason": "XML 无该期限"})
                        continue
                    py = _num(prev.get(config.TREASURY_TENOR_FIELD[tenor])) if prev else None
                    quotes.append(_quote(
                        tenor, tenor + " UST Yield", y, py, None, None,
                        open=None, high=None, low=None, volume=None, currency="%",
                        quote_time=as_of, group="US Treasury", extra={"tenor": tenor}))
            else:
                skipped.append({"symbol": "nominal", "reason": "XML 无 entry"})
        except ET.ParseError as e:
            skipped.append({"symbol": "nominal", "reason": "XML 解析失败: %s" % e})
    else:
        skipped.append({"symbol": "nominal", "reason": rn.get("error")})

    if rr["ok"]:
        try:
            real_rows = _parse_treasury(rr["body"])
            if real_rows:
                last = real_rows[-1]
                prev = real_rows[-2] if len(real_rows) > 1 else None
                for tenor, fld in config.TREASURY_REAL_FIELD.items():
                    v = _num(last.get(fld))
                    if v is None:
                        continue
                    pv = _num(prev.get(fld)) if prev else None
                    quotes.append(_quote(
                        "REAL" + tenor, tenor + " TIPS Real Yield", v, pv, None, None,
                        open=None, high=None, low=None, volume=None, currency="%",
                        quote_time=(last.get("NEW_DATE") or "")[:10], group="TIPS",
                        extra={"tenor": tenor, "real": True}))
        except ET.ParseError as e:
            skipped.append({"symbol": "real", "reason": "XML 解析失败: %s" % e})
    else:
        skipped.append({"symbol": "real", "reason": rr.get("error")})

    by = {q["symbol"]: q["last"] for q in quotes if q.get("last") is not None}
    by_prev = {q["symbol"]: q["prev_close"] for q in quotes if q.get("prev_close") is not None}

    def _derived_curve_quote(symbol, name, val, prev_val, group, extra):
        chg = round(val - prev_val, 4) if prev_val is not None else None
        return {
            "symbol": symbol, "name": name,
            "last": round(val, 4), "prev_close": round(prev_val, 4) if prev_val is not None else None,
            "change": chg, "change_pct": None, "open": None, "high": None,
            "low": None, "volume": None, "currency": "%", "quote_time": as_of,
            "group": group, "extra": extra,
        }

    # 期限利差 2s10s, 3m10y
    for label, a, b in [("2S10S", "10Y", "2Y"), ("3M10Y", "10Y", "3M")]:
        if a in by and b in by:
            pv = (by_prev[a] - by_prev[b]) if (a in by_prev and b in by_prev) else None
            quotes.append(_derived_curve_quote(
                label, label + " Spread", by[a] - by[b], pv, "Curve", {"spread": [a, b]}))

    # 蝶式曲率 2s5s10s = 2*5Y - (2Y + 10Y)
    if "2Y" in by and "5Y" in by and "10Y" in by:
        bfly = 2.0 * by["5Y"] - (by["2Y"] + by["10Y"])
        pv = (2.0 * by_prev["5Y"] - (by_prev["2Y"] + by_prev["10Y"])
              if ("2Y" in by_prev and "5Y" in by_prev and "10Y" in by_prev) else None)
        quotes.append(_derived_curve_quote(
            "2S5S10S", "2s5s10s Butterfly", bfly, pv, "Curve", {"butterfly": ["2Y", "5Y", "10Y"]}))

    # 盈亏平衡通胀 Breakeven Inflation (Nominal - TIPS Real)
    for tenor in ["5Y", "10Y", "20Y", "30Y"]:
        rkey = "REAL" + tenor
        if tenor in by and rkey in by:
            bei = by[tenor] - by[rkey]
            pv = (by_prev[tenor] - by_prev[rkey]
                  if (tenor in by_prev and rkey in by_prev) else None)
            quotes.append(_derived_curve_quote(
                "BEI" + tenor, tenor + " Breakeven Inflation", bei, pv, "Inflation",
                {"breakeven": tenor}))

    # 5y5y 远期盈亏平衡通胀 ≈ 2 * BEI10Y - BEI5Y
    bei_by = {q["symbol"]: q["last"] for q in quotes if q["symbol"].startswith("BEI")}
    bei_prev = {q["symbol"]: q["prev_close"] for q in quotes
                if q["symbol"].startswith("BEI") and q.get("prev_close") is not None}
    if "BEI10Y" in bei_by and "BEI5Y" in bei_by:
        fwd = 2.0 * bei_by["BEI10Y"] - bei_by["BEI5Y"]
        pv = (2.0 * bei_prev["BEI10Y"] - bei_prev["BEI5Y"]
              if ("BEI10Y" in bei_prev and "BEI5Y" in bei_prev) else None)
        quotes.append(_derived_curve_quote(
            "5Y5Y_BEI", "5y5y Forward Breakeven", fwd, pv, "Inflation",
            {"forward_breakeven": ["5Y", "10Y"]}))

    curve_history = _build_curve_history(nom_rows, real_rows)
    lats = [x for x in [rn.get("latency_ms"), rr.get("latency_ms")] if x is not None]
    return _env("BONDS", "US Treasury", url_n, rn["ok"], quotes, skipped,
                error=rn.get("error"), status=rn.get("status"),
                fetched_at=rn.get("fetched_at"), latency_ms=max(lats) if lats else None,
                as_of=as_of, curve_history=curve_history)


# -------------------------------------------------------------------- CRYPTO
def _crypto_failover_okx(coins):
    """备源 1：OKX SPOT 全量 ticker（SPEC-DASH §2.1 已实测可达）。"""
    url = config.OKX_SPOT_TICKERS
    res = net.fetch(url)
    quotes, skipped = [], []
    if not res["ok"]:
        return _env("CRYPTO", "okx (failover)", url, False, [], skipped,
                    error=res.get("error"), status=res.get("status"),
                    fetched_at=res.get("fetched_at"), latency_ms=res.get("latency_ms"))
    try:
        payload = json.loads(res["body"]).get("data") or []
    except (ValueError, AttributeError) as e:
        return _env("CRYPTO", "okx (failover)", url, False, [], skipped,
                    error="OKX JSON 解析失败: %s" % e, status=res.get("status"),
                    fetched_at=res.get("fetched_at"))
    seen = {row.get("instId"): row for row in payload}
    for c in coins:
        row = seen.get(c + "-USDT")
        if not row:
            skipped.append({"symbol": c, "reason": "okx 未返回该交易对"})
            continue
        last = _num(row.get("last"))
        op = _num(row.get("open24h"))
        quotes.append(_quote(
            c, config.CRYPTO_NAMES.get(c, c), last, op, None, None,
            open=op, high=_num(row.get("high24h")), low=_num(row.get("low24h")),
            volume=_num(row.get("vol24h")), currency="USD", quote_time=None,
            group="Crypto Spot",
            extra={"quote_volume": _num(row.get("volCcy24h")), "window": "24h",
                   "failover": True}))
    return _env("CRYPTO", "okx (failover)", url, True, quotes, skipped,
                error=None if quotes else "okx 返回为空", status=res.get("status"),
                fetched_at=res.get("fetched_at"), latency_ms=res.get("latency_ms"))


def _crypto_failover_bybit(coins):
    """备源 2：Bybit SPOT ticker（SPEC-DASH §2.1 已实测可达）。"""
    url = config.BYBIT_SPOT_TICKERS
    res = net.fetch(url)
    quotes, skipped = [], []
    if not res["ok"]:
        return _env("CRYPTO", "bybit (failover)", url, False, [], skipped,
                    error=res.get("error"), status=res.get("status"),
                    fetched_at=res.get("fetched_at"), latency_ms=res.get("latency_ms"))
    try:
        payload = ((json.loads(res["body"]).get("result") or {}).get("list")) or []
    except (ValueError, AttributeError) as e:
        return _env("CRYPTO", "bybit (failover)", url, False, [], skipped,
                    error="Bybit JSON 解析失败: %s" % e, status=res.get("status"),
                    fetched_at=res.get("fetched_at"))
    seen = {row.get("symbol"): row for row in payload}
    for c in coins:
        row = seen.get(c + "USDT")
        if not row:
            skipped.append({"symbol": c, "reason": "bybit 未返回该交易对"})
            continue
        last = _num(row.get("lastPrice"))
        prev = _num(row.get("prevPrice24h"))
        pct_raw = _num(row.get("price24hPcnt"))
        pct = round(pct_raw * 100.0, 4) if pct_raw is not None else None
        quotes.append(_quote(
            c, config.CRYPTO_NAMES.get(c, c), last, prev, None, pct,
            open=prev, high=_num(row.get("highPrice24h")), low=_num(row.get("lowPrice24h")),
            volume=_num(row.get("volume24h")), currency="USD", quote_time=None,
            group="Crypto Spot",
            extra={"quote_volume": _num(row.get("turnover24h")), "window": "24h",
                   "failover": True}))
    return _env("CRYPTO", "bybit (failover)", url, True, quotes, skipped,
                error=None if quotes else "bybit 返回为空", status=res.get("status"),
                fetched_at=res.get("fetched_at"), latency_ms=res.get("latency_ms"))


def crypto():
    coins = config.get_universe()["CRYPTO"]
    syms = [config.CRYPTO_SYMBOLS.get(c, c + "USDT") for c in coins]
    # 必须紧凑编码：json.dumps 默认分隔符含空格，binance 会以 HTTP 400 拒绝（已实测）
    url = config.BINANCE_24HR.format(
        symbols=urllib.parse.quote(json.dumps(syms, separators=(",", ":")), safe=""))
    res = net.fetch(url)
    quotes, skipped = [], []
    if res["ok"]:
        try:
            payload = json.loads(res["body"])
        except ValueError as e:
            return _env("CRYPTO", "binance", url, False, [], skipped,
                        error="JSON 解析失败: %s" % e, status=res.get("status"),
                        fetched_at=res.get("fetched_at"))
        if isinstance(payload, dict):
            payload = [payload]
        seen = {row.get("symbol"): row for row in payload}
        for c in coins:
            pair = config.CRYPTO_SYMBOLS.get(c, c + "USDT")
            row = seen.get(pair)
            if not row:
                skipped.append({"symbol": c, "reason": "binance 未返回该交易对"})
                continue
            last = _num(row.get("lastPrice"))
            chg = _num(row.get("priceChange"))
            pct = _num(row.get("priceChangePercent"))
            prev = (last - chg) if (last is not None and chg is not None) else None
            quotes.append(_quote(
                c, config.CRYPTO_NAMES.get(c, c), last, prev, chg, pct,
                open=_num(row.get("openPrice")), high=_num(row.get("highPrice")),
                low=_num(row.get("lowPrice")), volume=_num(row.get("volume")),
                currency="USD", quote_time=None, group="Crypto Spot",
                extra={"quote_volume": _num(row.get("quoteVolume")), "window": "24h"}))
        return _env("CRYPTO", "binance", url, True, quotes, skipped, error=None,
                    status=res.get("status"), fetched_at=res.get("fetched_at"),
                    latency_ms=res.get("latency_ms"))

    # 主源失败时尝试备源自动故障切换（不隐藏切换事实，source 显式标注 failover）
    for fallback_fn in (_crypto_failover_okx, _crypto_failover_bybit):
        fb = fallback_fn(coins)
        if fb["ok"]:
            fb["primary_error"] = res.get("error")
            return fb

    return _env("CRYPTO", "binance", url, False, [], skipped, error=res.get("error"),
                status=res.get("status"), fetched_at=res.get("fetched_at"),
                latency_ms=res.get("latency_ms"))


# --------------------------------------------------------- CRYPTO DERIVATIVES
def crypto_derivatives(spot_quotes=None):
    """加密量化微结构：Binance USDT-M 永续资金费率、基差、持仓量 + OKX 跨所现货价差。

    失败不伪造数据，缺失字段一律为 None。
    """
    coins = config.get_universe()["CRYPTO"]
    spot_by = {q["symbol"]: q.get("last") for q in (spot_quotes or []) if q.get("last")}

    prem_res = net.fetch(config.BINANCE_FAPI_PREMIUM, timeout=8, retries=1)
    okx_res = net.fetch(config.OKX_SPOT_TICKERS, timeout=8, retries=1)

    prem_map = {}
    if prem_res["ok"]:
        try:
            for row in json.loads(prem_res["body"]):
                prem_map[row.get("symbol")] = row
        except (ValueError, TypeError):
            prem_res = dict(prem_res, ok=False, error="premiumIndex JSON 解析失败")

    okx_map = {}
    if okx_res["ok"]:
        try:
            for row in (json.loads(okx_res["body"]).get("data") or []):
                okx_map[row.get("instId")] = _num(row.get("last"))
        except (ValueError, TypeError, AttributeError):
            okx_res = dict(okx_res, ok=False, error="OKX ticker JSON 解析失败")

    # 并发抓取持仓量（仅在 premiumIndex 可用时，避免无谓超时）
    oi_map = {}
    if prem_res["ok"]:
        def _fetch_oi(c):
            pair = c + "USDT"
            r = net.fetch(config.BINANCE_FAPI_OI.format(symbol=pair), timeout=6, retries=0)
            if r["ok"]:
                try:
                    return c, _num(json.loads(r["body"]).get("openInterest"))
                except (ValueError, AttributeError):
                    return c, None
            return c, None

        with ThreadPoolExecutor(max_workers=5) as ex:
            for c, val in ex.map(_fetch_oi, coins):
                if val is not None:
                    oi_map[c] = val

    rows = []
    for c in coins:
        pair = c + "USDT"
        prow = prem_map.get(pair) or {}
        mark = _num(prow.get("markPrice"))
        index_px = _num(prow.get("indexPrice"))
        funding = _num(prow.get("lastFundingRate"))
        ann_funding = round(funding * 3.0 * 365.0 * 100.0, 2) if funding is not None else None
        basis_bps = (round((mark - index_px) / index_px * 10000.0, 2)
                     if (mark is not None and index_px not in (None, 0)) else None)

        oi_qty = oi_map.get(c)
        oi_usd = round(oi_qty * mark, 2) if (oi_qty is not None and mark is not None) else None

        spot_px = spot_by.get(c)
        okx_px = okx_map.get(c + "-USDT")
        disp_bps = None
        if spot_px and okx_px and (spot_px + okx_px) > 0:
            mid = (spot_px + okx_px) / 2.0
            disp_bps = round((okx_px - spot_px) / mid * 10000.0, 2)

        if any(x is not None for x in (mark, funding, oi_usd, okx_px)):
            rows.append({
                "symbol": c,
                "mark_price": mark,
                "index_price": index_px,
                "funding_rate": funding,
                "funding_pct_8h": round(funding * 100.0, 5) if funding is not None else None,
                "funding_ann_pct": ann_funding,
                "basis_bps": basis_bps,
                "next_funding_ms": prow.get("nextFundingTime"),
                "oi_contracts": oi_qty,
                "oi_usd": oi_usd,
                "spot_binance": spot_px,
                "spot_okx": okx_px,
                "dispersion_bps": disp_bps,
            })

    lats = [x for x in [prem_res.get("latency_ms"), okx_res.get("latency_ms")] if x is not None]
    errs = [e for e in [prem_res.get("error"), okx_res.get("error")] if e]
    return {
        "ok": bool(rows),
        "rows": rows,
        "source": "binance-fapi + okx",
        "endpoint": config.BINANCE_FAPI_PREMIUM,
        "fetched_at": prem_res.get("fetched_at") or okx_res.get("fetched_at"),
        "latency_ms": max(lats) if lats else None,
        "error": "; ".join(errs) if errs and not rows else None,
        "partial_error": "; ".join(errs) if errs and rows else None,
    }


def fetch_crypto_klines(symbol, interval="1h", limit=100):
    """抓取 Binance 现货 K 线用于历史波动率与相关性冷启动。"""
    pair = config.CRYPTO_SYMBOLS.get(symbol.upper(), symbol.upper() + "USDT")
    url = config.BINANCE_KLINES.format(symbol=pair, interval=interval, limit=int(limit))
    res = net.fetch(url, timeout=10, retries=1)
    if not res["ok"]:
        return []
    try:
        raw = json.loads(res["body"])
    except ValueError:
        return []
    out = []
    for k in raw:
        if not isinstance(k, list) or len(k) < 6:
            continue
        ts_ms = int(k[0])
        ts_iso = datetime.fromtimestamp(ts_ms / 1000.0).astimezone().isoformat(timespec="seconds")
        out.append({
            "ts": ts_iso,
            "open": _num(k[1]),
            "high": _num(k[2]),
            "low": _num(k[3]),
            "close": _num(k[4]),
            "volume": _num(k[5]),
        })
    return out


ADAPTERS = {
    "EQUITY": equities,
    "FX": fx,
    "COMMODITIES": commodities,
    "BONDS": bonds,
    "CRYPTO": crypto,
}
