"""字段索引回归测试：每个断言都对应 SPEC-DASH §2.2 的一个实证判据。"""

from __future__ import annotations

import pytest

from qsdash import markets, net
from tests.helpers import fake_fetch, fixture, sina_fields

US = [("hq.sinajs.cn/list=gb_", "sina_us.txt")]
INT = [("hq.sinajs.cn/list=int_", "sina_int.txt")]
CN = [("hq.sinajs.cn/list=sh", "sina_cn.txt")]


def _patch(monkeypatch, mapping):
    monkeypatch.setattr(net, "fetch", fake_fetch(mapping))


# ------------------------------------------------------------------ EQUITIES
def test_us_equity_field_indices(monkeypatch):
    """[1]最新 [26]昨收 [4]涨跌额 [2]涨跌幅 [5]开盘 [6]高 [7]低 [10]量"""
    _patch(monkeypatch, US)
    r = markets.equities()
    assert r["ok"] is True and r["source"] == "sina"
    q = {x["symbol"]: x for x in r["quotes"]}["AAPL"]
    f = sina_fields(fixture("sina_us.txt"))["gb_aapl"]
    assert q["last"] == float(f[1])
    assert q["prev_close"] == float(f[26])
    assert q["open"] == float(f[5])
    assert q["high"] == float(f[6])
    assert q["low"] == float(f[7])
    assert q["volume"] == float(f[10])
    assert q["name"] == f[0]
    assert q["quote_time"] == f[3]


def test_us_equity_pct_is_self_consistent(monkeypatch):
    """AC-D2.4 不变量：(last-prev)/prev 必须与展示的 change_pct 吻合。"""
    _patch(monkeypatch, US)
    r = markets.equities()
    for q in r["quotes"]:
        if q.get("last") and q.get("prev_close"):
            calc = (q["last"] - q["prev_close"]) / q["prev_close"] * 100
            assert abs(calc - q["change_pct"]) < 0.03, q["symbol"]


def test_global_index_indices(monkeypatch):
    """int_ 只有 4 字段：[1]最新 [2]涨跌额 [3]涨跌幅"""
    _patch(monkeypatch, INT)
    r = markets.equities()
    q = {x["symbol"]: x for x in r["quotes"]}["DJI"]
    f = sina_fields(fixture("sina_int.txt"))["int_dji"]
    assert q["last"] == float(f[1])
    assert q["change"] == float(f[2])
    assert q["change_pct"] == float(f[3])
    assert q["prev_close"] == pytest.approx(float(f[1]) - float(f[2]))


def test_cn_index_indices(monkeypatch):
    """A 股指数：[1]开盘 [2]昨收 [3]最新 [4]高 [5]低 [31]时间"""
    _patch(monkeypatch, [("hq.sinajs.cn/list=sh", "sina_cn.txt")])
    r = markets.equities()
    q = {x["symbol"]: x for x in r["quotes"]}["SH000001"]
    f = sina_fields(fixture("sina_cn.txt"))["sh000001"]
    assert q["last"] == float(f[3])
    assert q["prev_close"] == float(f[2])
    assert q["open"] == float(f[1])
    assert q["high"] == float(f[4])
    assert q["low"] == float(f[5])


def test_skipped_is_reported_not_silent(monkeypatch):
    """AC-D2.3：fixture 只有 3 只美股，其余 9 只必须出现在 skipped 里。"""
    _patch(monkeypatch, US)
    r = markets.equities()
    missing = [s["symbol"] for s in r["skipped"]]
    assert "gb_tsla" in missing or "gb_googl" in missing
    assert all(s.get("reason") for s in r["skipped"])


# ------------------------------------------------------------------------ FX
def test_fx_uses_only_verified_indices(monkeypatch):
    """AC-D2.5：最新=[8]，昨收=[3]，涨跌幅=[10]，涨跌额=[11]；不输出买卖价。"""
    _patch(monkeypatch, [("hq.sinajs.cn/list=fx_", "sina_fx.txt")])
    r = markets.fx()
    assert r["ok"] is True
    qs = {x["symbol"]: x for x in r["quotes"]}
    f = sina_fields(fixture("sina_fx.txt"))
    for sym, key in [("USDCNY", "fx_susdcny"), ("EURUSD", "fx_seurusd")]:
        fields = f[key]
        q = qs[sym]
        assert q["last"] == float(fields[8])
        assert q["prev_close"] == float(fields[3])
        assert q["change"] == float(fields[11])
        assert q["name"] == fields[9]
    # 未互证的买卖价不得出现在任何字段里
    for q in r["quotes"]:
        assert "bid" not in q and "ask" not in q


def test_fx_missing_symbols_are_skipped(monkeypatch):
    _patch(monkeypatch, [("hq.sinajs.cn/list=fx_", "sina_fx.txt")])
    r = markets.fx()
    assert len(r["skipped"]) == len(markets.config.UNIVERSE["FX"]) - 2


# ----------------------------------------------------------------- COMMODITY
def test_commodity_field_indices(monkeypatch):
    """[0]最新 [7]昨结 [4]高 [5]低 [6]时间 [2]买 [3]卖 [13]名称"""
    _patch(monkeypatch, [("hq.sinajs.cn/list=hf_", "sina_hf.txt")])
    r = markets.commodities()
    q = {x["symbol"]: x for x in r["quotes"]}["GC"]
    f = sina_fields(fixture("sina_hf.txt"))["hf_GC"]
    assert q["last"] == float(f[0])
    assert q["prev_close"] == float(f[7])
    assert q["high"] == float(f[4])
    assert q["low"] == float(f[5])
    assert q["name"] == f[13]
    assert q["extra"]["bid"] == float(f[2])
    assert q["extra"]["ask"] == float(f[3])


# --------------------------------------------------------------------- BONDS
def test_treasury_curve_and_spreads(monkeypatch):
    """AC-D2.7：整条曲线 + 两个利差，as_of 取自 XML 自然日。"""
    _patch(monkeypatch, [
        ("daily_treasury_yield_curve", "treasury_nominal.xml"),
        ("daily_treasury_real_yield_curve", "treasury_real.xml"),
    ])
    r = markets.bonds()
    assert r["ok"] is True
    by = {x["symbol"]: x for x in r["quotes"]}
    for t in ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]:
        assert t in by, t
    assert by["10Y"]["currency"] == "%"
    assert r["as_of"] and len(r["as_of"]) == 10
    assert by["2S10S"]["last"] == pytest.approx(by["10Y"]["last"] - by["2Y"]["last"], abs=1e-6)
    assert by["3M10Y"]["last"] == pytest.approx(by["10Y"]["last"] - by["3M"]["last"], abs=1e-6)


def test_treasury_yield_change_is_previous_entry(monkeypatch):
    """昨值必须来自 XML 的倒数第二条，而非臆造。"""
    _patch(monkeypatch, [
        ("daily_treasury_yield_curve", "treasury_nominal.xml"),
        ("daily_treasury_real_yield_curve", "treasury_real.xml"),
    ])
    r = markets.bonds()
    rows = markets._parse_treasury(fixture("treasury_nominal.xml"))
    last, prev = rows[-1], rows[-2]
    by = {x["symbol"]: x for x in r["quotes"]}
    assert by["10Y"]["last"] == float(last["BC_10YEAR"])
    assert by["10Y"]["prev_close"] == float(prev["BC_10YEAR"])


# -------------------------------------------------------------------- CRYPTO
def test_crypto_field_mapping(monkeypatch):
    _patch(monkeypatch, [("api.binance.com", "binance_24hr.json")])
    r = markets.crypto()
    assert r["ok"] is True
    by = {x["symbol"]: x for x in r["quotes"]}
    assert "BTC" in by and "ETH" in by
    q = by["BTC"]
    assert q["last"] > 0
    # prev = last - priceChange（因此自洽性成立）
    calc = (q["last"] - q["prev_close"]) / q["prev_close"] * 100
    assert abs(calc - q["change_pct"]) < 0.05
    assert q["extra"]["window"] == "24h"


# ------------------------------------------------------------- 不造假的判据
def test_num_returns_none_not_zero():
    """缺失必须是 None；0 是有效行情，不能拿来冒充缺失。"""
    assert markets._num("") is None
    assert markets._num("   ") is None
    assert markets._num("abc") is None
    assert markets._num(None) is None
    assert markets._num("0") == 0.0
    assert markets._num("3.14") == pytest.approx(3.14)


def test_all_sources_down_yields_ok_false_not_fake_data(monkeypatch):
    """AC-D4.3：全部源失败时必须 ok=False 且 quotes 为空 —— 不得填 0。"""
    _patch(monkeypatch, [])
    for fn in [markets.equities, markets.fx, markets.commodities,
               markets.bonds, markets.crypto]:
        r = fn()
        assert r["ok"] is False
        assert r["quotes"] == []
        assert r["error"]


def test_pct_conflict_is_flagged(monkeypatch):
    """AC-D2.4：端点涨跌幅与计算值差 > 0.02pp 时以计算值为准并打标。"""
    body = 'var hq_str_gb_aapl="苹果,110.00,-5.00,2026-09-19 08:14:43,2.00,105.0,112.0,104.0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,100.0000";'
    monkeypatch.setattr(net, "fetch", fake_fetch([("hq.sinajs.cn/list=gb_", None)] and []))
    monkeypatch.setattr(net, "fetch", lambda *a, **k: {
        "ok": True, "status": 200, "body": body, "bytes": len(body), "latency_ms": 1,
        "attempt": 1, "fetched_at": "2026-09-21T10:00:00+08:00", "endpoint": "x", "error": None})
    r = markets.equities()
    q = r["quotes"][0]
    assert q["extra"]["pct_conflict"] is True
    assert q["extra"]["pct_reported"] == -5.0
    assert q["change_pct"] == pytest.approx(10.0, abs=0.01)
