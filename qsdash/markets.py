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
         error=None, status=None, fetched_at=None, latency_ms=None, as_of=None):
    return {
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
    q = {"symbol": symbol, "name": name, "last": last, "prev_close": prev,
         "change": chg, "change_pct": pct}
    q.update(kw)
    if extra:
        q["extra"] = extra
    return q


# ------------------------------------------------------------------ EQUITIES
def equities():
    """三组 sina 前缀，三种布局（SPEC-DASH §2.2a/b/c）。"""
    u = config.UNIVERSE["EQUITY"]
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
                    quotes.append(_quote(
                        s.upper(), f[0], _num(f[1]), _num(f[26]), _num(f[4]), _num(f[2]),
                        open=_num(f[5]), high=_num(f[6]), low=_num(f[7]), volume=_num(f[10]),
                        currency="USD", quote_time=(f[3] or None), group=group, venue=venue,
                        extra={"h52": _num(f[8]), "l52": _num(f[9]),
                               "mktcap": _num(f[12]), "pe": _num(f[14])}))
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
    syms = config.UNIVERSE["FX"]
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
    syms = config.UNIVERSE["COMMODITIES"]
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
                quotes.append(_quote(
                    s.replace("hf_", "").upper(), f[13] or s, _num(f[0]), _num(f[7]),
                    None, None, open=_num(f[8]), high=_num(f[4]), low=_num(f[5]),
                    volume=None, currency="USD", quote_time=(f[6] or None),
                    group="Futures (Global)",
                    extra={"bid": _num(f[2]), "ask": _num(f[3]),
                           "date": f[12] if len(f) > 12 else None}))
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


def bonds():
    """美债收益率曲线（日频，AC-D2.7）。as_of = XML 自然日，通常滞后当前交易日。"""
    year = datetime.now().year
    url_n = config.TREASURY_NOMINAL.format(year=year)
    url_r = config.TREASURY_REAL.format(year=year)
    rn = net.fetch(url_n)
    rr = net.fetch(url_r)

    quotes, skipped = [], []
    as_of = None
    if rn["ok"]:
        try:
            rows = _parse_treasury(rn["body"])
            if rows:
                last = rows[-1]
                prev = rows[-2] if len(rows) > 1 else None
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
            rows = _parse_treasury(rr["body"])
            if rows:
                last = rows[-1]
                for tenor, fld in config.TREASURY_REAL_FIELD.items():
                    v = _num(last.get(fld))
                    if v is None:
                        continue
                    quotes.append(_quote(
                        "REAL" + tenor, tenor + " TIPS Real Yield", v, None, None, None,
                        open=None, high=None, low=None, volume=None, currency="%",
                        quote_time=(last.get("NEW_DATE") or "")[:10], group="TIPS",
                        extra={"tenor": tenor, "real": True}))
        except ET.ParseError as e:
            skipped.append({"symbol": "real", "reason": "XML 解析失败: %s" % e})
    else:
        skipped.append({"symbol": "real", "reason": rr.get("error")})

    by = {q["symbol"]: q["last"] for q in quotes if q.get("last") is not None}
    for label, a, b in [("2S10S", "10Y", "2Y"), ("3M10Y", "10Y", "3M")]:
        if a in by and b in by:
            quotes.append({"symbol": label, "name": label + " Spread",
                           "last": round(by[a] - by[b], 4), "prev_close": None,
                           "change": None, "change_pct": None, "open": None, "high": None,
                           "low": None, "volume": None, "currency": "%", "quote_time": as_of,
                           "group": "Curve", "extra": {"spread": [a, b]}})

    lats = [x for x in [rn.get("latency_ms"), rr.get("latency_ms")] if x is not None]
    return _env("BONDS", "US Treasury", url_n, rn["ok"], quotes, skipped,
                error=rn.get("error"), status=rn.get("status"),
                fetched_at=rn.get("fetched_at"), latency_ms=max(lats) if lats else None,
                as_of=as_of)


# -------------------------------------------------------------------- CRYPTO
def crypto():
    syms = [config.CRYPTO_SYMBOLS[c] for c in config.UNIVERSE["CRYPTO"]]
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
        for c in config.UNIVERSE["CRYPTO"]:
            row = seen.get(config.CRYPTO_SYMBOLS[c])
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
    return _env("CRYPTO", "binance", url, res["ok"], quotes, skipped, error=res.get("error"),
                status=res.get("status"), fetched_at=res.get("fetched_at"),
                latency_ms=res.get("latency_ms"))


ADAPTERS = {
    "EQUITY": equities,
    "FX": fx,
    "COMMODITIES": commodities,
    "BONDS": bonds,
    "CRYPTO": crypto,
}
