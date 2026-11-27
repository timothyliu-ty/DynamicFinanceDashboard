"""量化交易模块离线单元测试：
覆盖收益率曲线分析与 PCA、跨资产价差、SQLite 时序存储与 CSV 导出、
滚动波动率/Z-Score/相关性矩阵、加密故障切换与衍生品、新闻催化剂标注、
规则告警引擎、组合盯市风控及量化 HTTP API / 增量 SSE。
"""

from __future__ import annotations

import json
import threading
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from qsdash import alerts as alerts_mod
from qsdash import config, hub as hub_mod, markets, net, news, portfolio as pf_mod, quant
from qsdash.server import make_server
from qsdash.storage import TimeSeriesStore
from tests.helpers import fake_fetch


# ---------------------------------------------- 1. Yield Curve & Breakevens
def test_bonds_emits_breakevens_butterfly_and_curve_history(monkeypatch):
    monkeypatch.setattr(net, "fetch", fake_fetch([
        ("daily_treasury_yield_curve", "treasury_nominal.xml"),
        ("daily_treasury_real_yield_curve", "treasury_real.xml"),
    ]))
    r = markets.bonds()
    assert r["ok"] is True
    by = {q["symbol"]: q for q in r["quotes"]}
    # 盈亏平衡通胀 = 名义 - TIPS 实际
    assert "BEI10Y" in by and "BEI5Y" in by and "5Y5Y_BEI" in by
    assert by["BEI10Y"]["last"] == pytest.approx(by["10Y"]["last"] - by["REAL10Y"]["last"], abs=1e-4)
    assert by["BEI5Y"]["last"] == pytest.approx(by["5Y"]["last"] - by["REAL5Y"]["last"], abs=1e-4)
    assert by["5Y5Y_BEI"]["last"] == pytest.approx(2 * by["BEI10Y"]["last"] - by["BEI5Y"]["last"], abs=1e-4)
    # 蝶式曲率 2s5s10s = 2*5Y - (2Y + 10Y)
    assert "2S5S10S" in by
    expected_bfly = 2 * by["5Y"]["last"] - (by["2Y"]["last"] + by["10Y"]["last"])
    assert by["2S5S10S"]["last"] == pytest.approx(expected_bfly, abs=1e-4)

    # 离线 fixture 只有 3 个交易日：验证曲线提取正确且严格遵守不造假（样本不足时不硬算 Z/PCA）
    ch = r["curve_history"]
    assert len(ch) == 3
    yc = quant.analyze_yield_curve(ch)
    assert yc["ok"] is True
    assert yc["n_days"] == 3
    assert yc["snapshots"]["latest"] is not None
    assert yc["pca"] is None
    m_by = {m["symbol"]: m for m in yc["metrics"]}
    assert m_by["10Y"]["zscore_ytd"] is None


def test_yield_curve_pca_and_ytd_zscore():
    """充足历史（30 个交易日）下应准确算出 YTD Z-Score、1M 变动与 SVD 三因子 PCA。"""
    ch = []
    for i in range(30):
        dt = (datetime(2026, 8, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
        # 构造带水平平移、斜率变化与曲率微动的曲线序列
        lvl = 0.015 * i
        slp = 0.005 * ((i % 5) - 2)
        crv = 0.004 * ((i % 3) - 1)
        ch.append({
            "as_of": dt,
            "nominal": {
                "1M": 4.00 + lvl, "3M": 4.05 + lvl, "6M": 4.10 + lvl,
                "1Y": 4.15 + lvl, "2Y": 4.20 + lvl - slp,
                "3Y": 4.25 + lvl, "5Y": 4.35 + lvl + crv,
                "7Y": 4.45 + lvl, "10Y": 4.55 + lvl + slp,
                "20Y": 4.75 + lvl + slp, "30Y": 4.80 + lvl + 1.2 * slp,
            },
            "real": {"5Y": 2.00 + 0.5 * lvl, "10Y": 2.15 + 0.5 * lvl,
                     "20Y": 2.30 + 0.5 * lvl, "30Y": 2.35 + 0.5 * lvl},
        })
    yc = quant.analyze_yield_curve(ch)
    assert yc["ok"] is True and yc["n_days"] == 30
    assert yc["snapshots"]["1w"] is not None
    assert yc["snapshots"]["1m"] is not None
    assert yc["pca"] is not None
    ve = yc["pca"]["variance_explained_pct"]
    assert 0 < ve["level_pc1"] <= 100
    assert ve["level_pc1"] + ve["slope_pc2"] + ve["curvature_pc3"] <= 100.05
    m_by = {m["symbol"]: m for m in yc["metrics"]}
    assert m_by["10Y"]["zscore_ytd"] is not None and m_by["10Y"]["zscore_ytd"] > 1.0
    assert m_by["10Y"]["chg_1m_bps"] is not None
    assert m_by["BEI10Y"]["zscore_ytd"] is not None


# ---------------------------------------------- 2. Enriched Equity & Commodity
def test_equity_and_commodity_derived_quant_fields(monkeypatch):
    monkeypatch.setattr(net, "fetch", fake_fetch([
        ("hq.sinajs.cn/list=gb_", "sina_us.txt"),
        ("hq.sinajs.cn/list=hf_", "sina_hf.txt"),
    ]))
    eq = markets.equities()
    aapl = {q["symbol"]: q for q in eq["quotes"]}["AAPL"]
    assert "range_pct" in aapl["extra"]
    assert "pos_52w" in aapl["extra"]
    assert "dd_52w" in aapl["extra"]
    assert "dollar_vol" in aapl["extra"]
    assert aapl["extra"]["dd_52w"] <= 0.0 or aapl["last"] >= aapl["extra"]["h52"]

    cm = markets.commodities()
    gc = {q["symbol"]: q for q in cm["quotes"]}["GC"]
    assert "spread_bps" in gc["extra"]
    assert gc["extra"]["spread_bps"] >= 0
    assert "range_pct" in gc["extra"]


# ---------------------------------------------- 3. Cross-Asset Spreads & Regime
def test_cross_asset_spreads_and_macro_regime():
    classes = {
        "EQUITY": {"ok": True, "quotes": [
            {"symbol": "SP500", "last": 5800.0, "change_pct": 1.2},
            {"symbol": "NASDAQ", "last": 18500.0, "change_pct": 1.8},
            {"symbol": "SH000300", "last": 4000.0, "change_pct": 0.4},
            {"symbol": "HANGSENG", "last": 20000.0, "change_pct": 0.6},
        ]},
        "FX": {"ok": True, "quotes": [
            {"symbol": "USDCNY", "last": 7.1000, "change_pct": 0.0},
            {"symbol": "USDCNH", "last": 7.1250, "change_pct": 0.1},
        ]},
        "COMMODITIES": {"ok": True, "quotes": [
            {"symbol": "GC", "last": 2700.0, "change_pct": -0.5},
            {"symbol": "SI", "last": 30.0, "change_pct": 0.2},
            {"symbol": "HG", "last": 450.0, "change_pct": 1.5},
            {"symbol": "CL", "last": 75.0, "change_pct": 0.8},
            {"symbol": "NG", "last": 2.5, "change_pct": -0.4},
        ]},
        "BONDS": {"ok": True, "quotes": [
            {"symbol": "2S10S", "last": 0.35},
            {"symbol": "BEI10Y", "last": 2.30},
        ]},
        "CRYPTO": {"ok": True, "quotes": [
            {"symbol": "BTC", "last": 90000.0, "change_pct": 3.5},
            {"symbol": "ETH", "last": 3150.0, "change_pct": 5.0},
            {"symbol": "SOL", "last": 200.0, "change_pct": 6.5},
        ]},
    }
    spreads = {s["id"]: s for s in quant.compute_cross_asset_spreads(classes)}
    assert spreads["CNH_CNY"]["value"] == pytest.approx(250.0, abs=0.2)
    assert spreads["CNH_CNY"]["signal"] == "CNH DISCOUNT"
    assert spreads["GC_SI"]["value"] == pytest.approx(90.0, abs=0.01)
    assert spreads["CL_NG"]["value"] == pytest.approx(30.0, abs=0.01)
    assert spreads["ETH_BTC"]["value"] == pytest.approx(3150.0 / 90000.0, abs=1e-5)
    assert spreads["US_CN_EQ"]["value"] == pytest.approx(0.8, abs=0.01)

    regime = quant.compute_macro_regime(classes)
    assert regime["label"] == "RISK-ON"
    assert regime["score"] > 20
    assert regime["n_factors"] >= 4
    assert all("weight" in c and "score" in c for c in regime["components"])

    # 无数据时绝不伪造 0 分
    empty_reg = quant.compute_macro_regime({})
    assert empty_reg["score"] is None and empty_reg["label"] == "NO DATA"


# ---------------------------------------------- 4. SQLite Storage, Stats & Corr
def test_storage_rolling_stats_correlation_and_csv():
    st = TimeSeriesStore(db_path=":memory:", min_write_interval_s=0.0)
    t0 = datetime(2026, 11, 26, 10, 0, 0, tzinfo=timezone.utc)
    btc_px = [80000, 80400, 80200, 80900, 81500, 81200, 82000, 82600, 82400, 83500]
    eth_px = [3000, 3020, 3010, 3050, 3080, 3065, 3110, 3145, 3130, 3190]
    for i in range(len(btc_px)):
        ts = (t0 + timedelta(minutes=i)).isoformat(timespec="seconds")
        st.record_quotes("CRYPTO", [
            {"symbol": "BTC", "last": btc_px[i], "prev_close": 80000, "change_pct": 1.0},
            {"symbol": "ETH", "last": eth_px[i], "prev_close": 3000, "change_pct": 1.2},
        ], ts_utc=ts, force=True)

    series = st.get_series("BTC", asset_class="CRYPTO", limit=50)
    assert len(series) == len(btc_px)
    assert series[-1]["last"] == 83500.0

    csv_text = st.export_csv(symbol="BTC")
    lines = [ln for ln in csv_text.strip().splitlines() if ln]
    assert lines[0].startswith("ts_utc,asset_class,symbol,last")
    assert len(lines) == len(btc_px) + 1

    recent = st.get_recent_prices_by_class(limit_per_symbol=50)
    sstats = quant.compute_symbol_stats(recent)
    btc_st = sstats["CRYPTO:BTC"]
    assert btc_st["n"] == 10
    assert btc_st["zscore"] is not None and btc_st["zscore"] > 1.0
    assert btc_st["vol_bps"] is not None and btc_st["vol_bps"] > 0
    assert len(btc_st["sparkline"]) == 10

    corr = quant.compute_correlation_matrix(recent, min_obs=5)
    assert corr["ok"] is True
    assert set(corr["symbols"]) == {"BTC", "ETH"}
    # BTC 与 ETH 同步上涨，正相关性应显著高于 0.9
    assert corr["matrix"][0][1] > 0.9

    # 样本不足时不得伪造相关性
    small = quant.compute_correlation_matrix({("CRYPTO", "BTC"): recent[("CRYPTO", "BTC")][:2]}, min_obs=5)
    assert small["ok"] is False
    st.close()


# ---------------------------------------------- 5. Crypto Failover & Derivatives
def test_crypto_automatic_failover_to_okx(monkeypatch):
    okx_payload = json.dumps({
        "code": "0",
        "data": [
            {"instId": "BTC-USDT", "last": "85000", "open24h": "84000",
             "high24h": "86000", "low24h": "83500", "vol24h": "1234", "volCcy24h": "100000000"},
            {"instId": "ETH-USDT", "last": "3200", "open24h": "3100",
             "high24h": "3250", "low24h": "3050", "vol24h": "5678", "volCcy24h": "18000000"},
        ],
    })

    def fake(url, **kw):
        if "api.binance.com" in url:
            return {"ok": False, "status": 503, "body": "", "error": "HTTP 503",
                    "fetched_at": "2026-11-26T10:00:00+00:00", "latency_ms": 10}
        if "okx.com" in url:
            return {"ok": True, "status": 200, "body": okx_payload, "error": None,
                    "fetched_at": "2026-11-26T10:00:00+00:00", "latency_ms": 20}
        return {"ok": False, "status": 503, "body": "", "error": "down"}

    monkeypatch.setattr(net, "fetch", fake)
    r = markets.crypto()
    assert r["ok"] is True
    assert "failover" in r["source"]
    assert r["primary_error"] == "HTTP 503"
    by = {q["symbol"]: q for q in r["quotes"]}
    assert by["BTC"]["last"] == 85000.0
    assert by["BTC"]["extra"]["failover"] is True


def test_crypto_derivatives_funding_basis_and_dispersion(monkeypatch):
    prem = json.dumps([
        {"symbol": "BTCUSDT", "markPrice": "90090.0", "indexPrice": "90000.0",
         "lastFundingRate": "0.0003", "nextFundingTime": 1764201600000},
    ])
    oi = json.dumps({"symbol": "BTCUSDT", "openInterest": "50000"})
    okx = json.dumps({"data": [{"instId": "BTC-USDT", "last": "90180.0"}]})

    def fake(url, **kw):
        if "premiumIndex" in url:
            return {"ok": True, "status": 200, "body": prem, "error": None,
                    "fetched_at": "2026-11-26T10:00:00+00:00", "latency_ms": 15}
        if "openInterest" in url:
            return {"ok": True, "status": 200, "body": oi, "error": None,
                    "fetched_at": "2026-11-26T10:00:00+00:00", "latency_ms": 12}
        if "okx.com" in url:
            return {"ok": True, "status": 200, "body": okx, "error": None,
                    "fetched_at": "2026-11-26T10:00:00+00:00", "latency_ms": 18}
        return {"ok": False, "status": 404, "body": "", "error": "miss"}

    monkeypatch.setattr(net, "fetch", fake)
    res = markets.crypto_derivatives(spot_quotes=[{"symbol": "BTC", "last": 90000.0}])
    assert res["ok"] is True
    btc = {r["symbol"]: r for r in res["rows"]}["BTC"]
    # 0.0003 * 3 * 365 * 100 = 32.85% annualized
    assert btc["funding_ann_pct"] == pytest.approx(32.85, abs=0.05)
    # (90090 - 90000) / 90000 * 10000 = 10.0 bps
    assert btc["basis_bps"] == pytest.approx(10.0, abs=0.1)
    # (90180 - 90000) / 90090 * 10000 ≈ 19.98 bps
    assert btc["dispersion_bps"] == pytest.approx(19.98, abs=0.1)
    assert btc["oi_usd"] == pytest.approx(50000.0 * 90090.0, rel=1e-4)


# ---------------------------------------------- 6. News Tagging
def test_news_ticker_event_and_sentiment_tagging():
    t1 = news.tag_headline("Nvidia surges to record high after earnings beat as Fed hints rate cut")
    assert "NVDA" in t1["tickers"]
    assert "EARNINGS" in t1["events"]
    assert "FOMC/FED" in t1["events"]
    assert t1["sentiment"]["label"] == "BULL"
    assert t1["sentiment"]["score"] > 0

    t2 = news.tag_headline("Bitcoin plunges amid SEC lawsuit and inflation warning")
    assert "BTC" in t2["tickers"]
    assert "REGULATION" in t2["events"]
    assert "INFLATION" in t2["events"]
    assert t2["sentiment"]["label"] == "BEAR"
    assert t2["sentiment"]["score"] < 0


# ---------------------------------------------- 7. Alert Engine
def test_alert_engine_rules_and_cooldown(tmp_path):
    ae = alerts_mod.AlertEngine(path=str(tmp_path / "alerts.json"))
    ae._rules = []
    ae.add_rule({"id": "r1", "type": "price_above", "target": "BTC", "threshold": 85000, "cooldown_s": 300})
    ae.add_rule({"id": "r2", "type": "spread_below", "target": "2S10S", "threshold": 0.0, "cooldown_s": 300})
    ae.add_rule({"id": "r3", "type": "news_keyword", "target": "FOMC", "cooldown_s": 300})

    classes = {
        "CRYPTO": {"ok": True, "quotes": [{"symbol": "BTC", "last": 91000.0, "change_pct": 2.0}]},
        "NEWS": {"ok": True, "items": [{"title": "FOMC delivers surprise cut", "link": "https://x/1", "source": "CNBC"}]},
    }
    q_snap = {"spreads": [{"id": "2S10S", "name": "UST 2s10s", "value": -12.0, "unit": "bps"}]}

    fired1 = ae.evaluate(classes, q_snap)
    assert len(fired1) == 3
    # 冷却时间内同一规则不得重复刷屏
    fired2 = ae.evaluate(classes, q_snap)
    assert len(fired2) == 0

    assert ae.delete_rule("r1") is True
    assert ae.delete_rule("nope") is False


# ---------------------------------------------- 8. Portfolio Risk Overlay
def test_portfolio_mtm_and_no_faking_unpriced(tmp_path):
    pf = pf_mod.PortfolioBook(path=str(tmp_path / "portfolio.json"))
    pf.add_position({"id": "p1", "symbol": "BTC", "side": "LONG", "qty": 2.0, "entry_price": 80000.0})
    pf.add_position({"id": "p2", "symbol": "AAPL", "side": "SHORT", "qty": 100.0, "entry_price": 220.0})
    pf.add_position({"id": "p3", "symbol": "MISSING_SYM", "side": "LONG", "qty": 10.0, "entry_price": 50.0})

    classes = {
        "CRYPTO": {"ok": True, "quotes": [{"symbol": "BTC", "last": 90000.0, "change": 1500.0}]},
        "EQUITY": {"ok": True, "quotes": [{"symbol": "AAPL", "last": 210.0, "change": -2.0}]},
    }
    val = pf.value(classes)
    by = {p["id"]: p for p in val["positions"]}
    assert by["p1"]["unrealized_pnl"] == pytest.approx(20000.0)
    assert by["p1"]["day_pnl"] == pytest.approx(3000.0)
    # Short AAPL from 220 -> 210: +10 * 100 = +1000
    assert by["p2"]["unrealized_pnl"] == pytest.approx(1000.0)
    # 未报价标的必须 priced=False 且 pnl=None，绝不填 0
    assert by["p3"]["priced"] is False
    assert by["p3"]["unrealized_pnl"] is None

    s = val["summary"]
    assert s["priced"] == 2 and s["unpriced"] == 1
    assert s["long_notional"] == pytest.approx(180000.0)
    assert s["short_notional"] == pytest.approx(21000.0)
    assert s["gross_exposure"] == pytest.approx(201000.0)
    assert s["net_exposure"] == pytest.approx(159000.0)
    assert s["unrealized_pnl"] == pytest.approx(21000.0)
    assert 0 < s["concentration_hhi"] <= 1.0


# ---------------------------------------------- 9. HTTP Quant API & Delta SSE
def test_quant_http_endpoints_and_delta_hub(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WATCHLIST_PATH", str(tmp_path / "watchlist.json"))
    hub = hub_mod.Hub(
        db_path=str(tmp_path / "h.sqlite3"),
        alerts_path=str(tmp_path / "a.json"),
        portfolio_path=str(tmp_path / "p.json"),
    )
    monkeypatch.setattr(hub_mod, "_fetch_class", lambda cls: (
        {"asset_class": "NEWS", "ok": True, "items": [
            {"title": "Apple beats earnings", "link": "https://x/1", "source": "CNBC",
             "tickers": ["AAPL"], "events": ["EARNINGS"], "sentiment": {"label": "BULL", "score": 1.0}}
        ], "feeds": [], "skipped": [], "error": None, "source": "RSS", "fetched_at": "2026-11-26T10:00:00+00:00"}
        if cls == "NEWS" else
        {"asset_class": cls, "ok": True, "quotes": [
            {"symbol": "BTC" if cls == "CRYPTO" else "AAPL", "name": "Test", "last": 100.0,
             "prev_close": 98.0, "change": 2.0, "change_pct": 2.04}
        ], "skipped": [], "error": None, "source": "mock", "fetched_at": "2026-11-26T10:00:00+00:00"}
    ))
    hub.refresh_all()

    # Delta 检测：只刷新 CRYPTO 时，delta_since 只应返回 CRYPTO
    v0 = dict(hub.snapshot()["class_versions"])
    hub.refresh("CRYPTO")
    delta = hub.delta_since(v0)
    assert list(delta["changed"].keys()) == ["CRYPTO"]
    assert "NEWS" not in delta["changed"]

    srv = make_server(hub, "127.0.0.1", 0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = "http://127.0.0.1:%d" % port
    try:
        # GET /api/quant
        with urllib.request.urlopen(base + "/api/quant", timeout=5) as r:
            assert r.status == 200
            qd = json.loads(r.read().decode("utf-8"))
            assert "regime" in qd and "spreads" in qd and "storage" in qd

        # GET /api/history & /api/export.csv
        with urllib.request.urlopen(base + "/api/history?symbol=BTC", timeout=5) as r:
            hd = json.loads(r.read().decode("utf-8"))
            assert hd["ok"] is True and hd["count"] >= 1
        with urllib.request.urlopen(base + "/api/export.csv?symbol=BTC", timeout=5) as r:
            csv_raw = r.read().decode("utf-8")
            assert "ts_utc,asset_class,symbol,last" in csv_raw and "BTC" in csv_raw

        # POST / GET / DELETE /api/portfolio
        req = urllib.request.Request(
            base + "/api/portfolio",
            data=json.dumps({"symbol": "BTC", "side": "LONG", "qty": 1.5, "entry_price": 90.0}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            pd_res = json.loads(r.read().decode("utf-8"))
            assert pd_res["ok"] is True
            pid = pd_res["position"]["id"]
            assert pd_res["portfolio"]["summary"]["unrealized_pnl"] == pytest.approx(15.0)

        del_req = urllib.request.Request(base + "/api/portfolio?id=" + pid, method="DELETE")
        with urllib.request.urlopen(del_req, timeout=5) as r:
            assert json.loads(r.read().decode("utf-8"))["ok"] is True

        # POST / GET /api/watchlist
        wreq = urllib.request.Request(
            base + "/api/watchlist",
            data=json.dumps({"us_equity": ["amd"], "crypto": ["ARB"]}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(wreq, timeout=5) as r:
            wd = json.loads(r.read().decode("utf-8"))
            assert wd["ok"] is True
            assert "amd" in wd["universe"]["EQUITY"]["us"]
            assert "ARB" in wd["universe"]["CRYPTO"]
    finally:
        srv.shutdown()
        srv.server_close()
        hub.stop()
