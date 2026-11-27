"""量化分析引擎（numpy / pandas / scipy）。

职责：
1. 收益率曲线分析：名义 / TIPS / 盈亏平衡通胀 / 5y5y 远期 / 蝶式曲率、
   1W/1M/3M 曲线平移、YTD Z-Score & 分位数、三因子 PCA（水平/斜率/曲率）
2. 跨资产宏观与统计套利价差：CNH-CNY 离在岸基差、金银比 GC/SI、铜金比 HG/GC、
   油气比 CL/NG、ETH/BTC、SOL/ETH、中美股指收益差
3. 宏观 Risk-On / Risk-Off 透明因子合成（逐项披露贡献，无黑盒）
4. 个股/标的统计信号：滚动 Z-Score、分位数、实现波动率（bps）、迷你走势 sparkline
5. 跨资产滚动相关性矩阵（pandas 对齐收益，样本不足返回 None 绝不填 0）
6. 加密永续资金费率、基差、持仓量与跨所现货价差排序
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from . import config

CURVE_TENORS = ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
PCA_TENORS = ["3M", "1Y", "2Y", "5Y", "10Y", "30Y"]
CORR_BENCHMARKS = [
    ("EQUITY", "SP500"), ("EQUITY", "NASDAQ"), ("EQUITY", "NVDA"), ("EQUITY", "SH000300"),
    ("FX", "USDCNY"), ("FX", "EURUSD"), ("FX", "USDJPY"),
    ("COMMODITIES", "GC"), ("COMMODITIES", "CL"), ("COMMODITIES", "HG"),
    ("CRYPTO", "BTC"), ("CRYPTO", "ETH"), ("CRYPTO", "SOL"),
]


def _f(v):
    if v is None:
        return None
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _r(v, nd=4):
    x = _f(v)
    return round(x, nd) if x is not None else None


def _quote_map(classes):
    """构建 (cls, symbol) -> quote 与 symbol -> quote 的快速索引。"""
    by_pair = {}
    by_sym = {}
    for cls, payload in (classes or {}).items():
        if cls == "NEWS" or not payload:
            continue
        for q in (payload.get("quotes") or []):
            sym = q.get("symbol")
            if not sym:
                continue
            by_pair[(cls, sym)] = q
            by_sym.setdefault(sym, q)
    return by_pair, by_sym


# ------------------------------------------------------------ 1. Yield Curve
def _series_stats(values):
    """给定时间正序数值序列，返回最新值的 Z-Score、分位数、极值、均值与样本量。"""
    arr = np.array([v for v in values if _f(v) is not None], dtype=float)
    n = int(arr.size)
    if n == 0:
        return {"n": 0, "zscore": None, "pct_rank": None, "mean": None,
                "std": None, "min": None, "max": None}
    last = float(arr[-1])
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if n >= 2 else 0.0
    z = (last - mean) / std if (n >= 5 and std > 1e-12) else None
    pct = float(scipy_stats.percentileofscore(arr, last, kind="weak")) if n >= 5 else None
    return {
        "n": n,
        "zscore": _r(z, 2),
        "pct_rank": _r(pct, 1),
        "mean": _r(mean, 4),
        "std": _r(std, 4) if n >= 2 else None,
        "min": _r(float(np.min(arr)), 4),
        "max": _r(float(np.max(arr)), 4),
    }


def analyze_yield_curve(curve_history):
    """分析美债日频曲线：当期 vs 1W/1M/3M、YTD Z-Score、三因子 SVD PCA。"""
    if not curve_history:
        return {"ok": False, "n_days": 0, "tenors": CURVE_TENORS,
                "snapshots": {}, "metrics": [], "pca": None}

    n_days = len(curve_history)
    latest = curve_history[-1]

    def _pick(offset):
        idx = max(0, n_days - 1 - offset)
        return curve_history[idx]

    snapshots = {
        "latest": latest,
        "1w": _pick(5) if n_days > 5 else None,
        "1m": _pick(21) if n_days > 21 else None,
        "3m": _pick(63) if n_days > 63 else None,
    }

    # 提取各关键期限与利差的 YTD 序列
    def _extract(fn):
        return [fn(row) for row in curve_history]

    metric_defs = [
        ("2Y",       "2Y UST",         lambda r: (r.get("nominal") or {}).get("2Y")),
        ("5Y",       "5Y UST",         lambda r: (r.get("nominal") or {}).get("5Y")),
        ("10Y",      "10Y UST",        lambda r: (r.get("nominal") or {}).get("10Y")),
        ("30Y",      "30Y UST",        lambda r: (r.get("nominal") or {}).get("30Y")),
        ("2S10S",    "10Y-2Y Slope",   lambda r: _diff(r.get("nominal"), "10Y", "2Y")),
        ("3M10Y",    "10Y-3M Slope",   lambda r: _diff(r.get("nominal"), "10Y", "3M")),
        ("2S5S10S",  "2s5s10s Bfly",   lambda r: _bfly(r.get("nominal"))),
        ("BEI5Y",    "5Y Breakeven",   lambda r: _bei(r, "5Y")),
        ("BEI10Y",   "10Y Breakeven",  lambda r: _bei(r, "10Y")),
        ("5Y5Y_BEI", "5y5y Fwd BEI",   lambda r: _fwd5y5y(r)),
    ]

    metrics = []
    for sym, label, fn in metric_defs:
        seq = _extract(fn)
        valid = [x for x in seq if x is not None]
        if not valid:
            continue
        st = _series_stats(valid)
        last_v = valid[-1]
        chg_1d = round((last_v - valid[-2]) * 100.0, 1) if len(valid) >= 2 else None
        chg_1m = round((last_v - valid[-22]) * 100.0, 1) if len(valid) >= 22 else None
        metrics.append({
            "symbol": sym,
            "label": label,
            "last": _r(last_v, 3),
            "chg_1d_bps": chg_1d,
            "chg_1m_bps": chg_1m,
            "zscore_ytd": st["zscore"],
            "pct_rank_ytd": st["pct_rank"],
            "ytd_min": st["min"],
            "ytd_max": st["max"],
            "n": st["n"],
        })

    # Rates PCA（Level / Slope / Curvature）基于真实日变动矩阵
    pca = None
    mat_rows = []
    for row in curve_history:
        nom = row.get("nominal") or {}
        if all(t in nom for t in PCA_TENORS):
            mat_rows.append([float(nom[t]) for t in PCA_TENORS])
    if len(mat_rows) >= 15:
        mat = np.array(mat_rows, dtype=float)
        diffs = np.diff(mat, axis=0) * 100.0  # 日变动（bps）
        centered = diffs - np.mean(diffs, axis=0)
        try:
            _, svals, vt = np.linalg.svd(centered, full_matrices=False)
            var = svals ** 2
            tot = float(np.sum(var))
            if tot > 0:
                expl = (var / tot * 100.0).tolist()
                pca = {
                    "tenors": PCA_TENORS,
                    "n_obs": int(diffs.shape[0]),
                    "variance_explained_pct": {
                        "level_pc1": _r(expl[0], 2),
                        "slope_pc2": _r(expl[1], 2) if len(expl) > 1 else None,
                        "curvature_pc3": _r(expl[2], 2) if len(expl) > 2 else None,
                    },
                    "daily_vol_bps": {
                        t: _r(float(np.std(diffs[:, i], ddof=1)), 2)
                        for i, t in enumerate(PCA_TENORS)
                    },
                }
        except np.linalg.LinAlgError:
            pca = None

    return {
        "ok": True,
        "as_of": latest.get("as_of"),
        "n_days": n_days,
        "tenors": CURVE_TENORS,
        "snapshots": snapshots,
        "metrics": metrics,
        "pca": pca,
    }


def _diff(d, a, b):
    if not d or a not in d or b not in d:
        return None
    return float(d[a]) - float(d[b])


def _bfly(d):
    if not d or "2Y" not in d or "5Y" not in d or "10Y" not in d:
        return None
    return 2.0 * float(d["5Y"]) - (float(d["2Y"]) + float(d["10Y"]))


def _bei(row, tenor):
    nom = (row.get("nominal") or {}).get(tenor)
    real = (row.get("real") or {}).get(tenor)
    if nom is None or real is None:
        return None
    return float(nom) - float(real)


def _fwd5y5y(row):
    b10 = _bei(row, "10Y")
    b5 = _bei(row, "5Y")
    if b10 is None or b5 is None:
        return None
    return 2.0 * b10 - b5


# --------------------------------------------------------- 2. Cross-Asset
def compute_cross_asset_spreads(classes, curve_analytics=None):
    """计算宏观与跨资产统计套利价差/比值。缺少任一条腿则跳过，绝不填 0。"""
    by_pair, _ = _quote_map(classes)
    curve_by = {m["symbol"]: m for m in ((curve_analytics or {}).get("metrics") or [])}

    def px(cls, sym):
        q = by_pair.get((cls, sym))
        return _f(q.get("last")) if q else None

    def pct(cls, sym):
        q = by_pair.get((cls, sym))
        return _f(q.get("change_pct")) if q else None

    spreads = []

    # 1. CNH - CNY 离在岸汇差（核心中国宏观/离岸流动性压力指标）
    cnh, cny = px("FX", "USDCNH"), px("FX", "USDCNY")
    if cnh is not None and cny is not None and cny > 0:
        pips = (cnh - cny) * 10000.0
        bps = (cnh - cny) / cny * 10000.0
        spreads.append({
            "id": "CNH_CNY",
            "name": "CNH-CNY Offshore Basis",
            "category": "FX / China",
            "value": _r(pips, 1),
            "unit": "pips",
            "secondary": _r(bps, 2),
            "secondary_unit": "bps",
            "legs": ["USDCNH", "USDCNY"],
            "signal": "CNH DISCOUNT" if pips > 150 else ("CNH PREMIUM" if pips < -150 else "BALANCED"),
        })

    # 2. Gold / Silver Ratio
    gc, si = px("COMMODITIES", "GC"), px("COMMODITIES", "SI")
    if gc is not None and si is not None and si > 0:
        ratio = gc / si
        spreads.append({
            "id": "GC_SI",
            "name": "Gold / Silver Ratio",
            "category": "Precious Metals",
            "value": _r(ratio, 2),
            "unit": "x",
            "secondary": None,
            "secondary_unit": None,
            "legs": ["GC", "SI"],
            "signal": "DEFENSIVE" if ratio > 85 else ("CYCLICAL" if ratio < 65 else "NEUTRAL"),
        })

    # 3. Copper / Gold Ratio (HG is US cents/lb -> USD/lb = HG/100; scaled *1000)
    hg = px("COMMODITIES", "HG")
    if hg is not None and gc is not None and gc > 0:
        cu_usd_lb = hg / 100.0
        cu_au = (cu_usd_lb / gc) * 1000.0
        spreads.append({
            "id": "HG_GC",
            "name": "Copper / Gold Ratio",
            "category": "Macro Growth",
            "value": _r(cu_au, 3),
            "unit": "x1000",
            "secondary": None,
            "secondary_unit": None,
            "legs": ["HG", "GC"],
            "signal": "GROWTH" if (pct("COMMODITIES", "HG") or 0) > (pct("COMMODITIES", "GC") or 0) else "HAVEN",
        })

    # 4. Crude Oil / Natural Gas Ratio
    cl, ng = px("COMMODITIES", "CL"), px("COMMODITIES", "NG")
    if cl is not None and ng is not None and ng > 0:
        spreads.append({
            "id": "CL_NG",
            "name": "WTI Crude / NatGas",
            "category": "Energy",
            "value": _r(cl / ng, 2),
            "unit": "x",
            "secondary": None,
            "secondary_unit": None,
            "legs": ["CL", "NG"],
            "signal": "OIL RICH" if (cl / ng) > 30 else "BALANCED",
        })

    # 5. ETH / BTC Ratio
    eth, btc = px("CRYPTO", "ETH"), px("CRYPTO", "BTC")
    if eth is not None and btc is not None and btc > 0:
        eb = eth / btc
        eth_p, btc_p = pct("CRYPTO", "ETH"), pct("CRYPTO", "BTC")
        rel = (eth_p - btc_p) if (eth_p is not None and btc_p is not None) else None
        spreads.append({
            "id": "ETH_BTC",
            "name": "ETH / BTC Ratio",
            "category": "Crypto Rotation",
            "value": _r(eb, 5),
            "unit": "BTC",
            "secondary": _r(rel, 2),
            "secondary_unit": "pp",
            "legs": ["ETH", "BTC"],
            "signal": "ALT OUTPERF" if (rel or 0) > 1.0 else ("BTC DOM" if (rel or 0) < -1.0 else "INLINE"),
        })

    # 6. SOL / ETH Ratio
    sol = px("CRYPTO", "SOL")
    if sol is not None and eth is not None and eth > 0:
        sol_p, eth_p = pct("CRYPTO", "SOL"), pct("CRYPTO", "ETH")
        rel = (sol_p - eth_p) if (sol_p is not None and eth_p is not None) else None
        spreads.append({
            "id": "SOL_ETH",
            "name": "SOL / ETH Ratio",
            "category": "Crypto Rotation",
            "value": _r(sol / eth, 5),
            "unit": "ETH",
            "secondary": _r(rel, 2),
            "secondary_unit": "pp",
            "legs": ["SOL", "ETH"],
            "signal": "SOL LEAD" if (rel or 0) > 1.0 else ("ETH LEAD" if (rel or 0) < -1.0 else "INLINE"),
        })

    # 7. US vs China Equity Relative Return (SP500 - CSI300)
    sp_p, csi_p = pct("EQUITY", "SP500"), pct("EQUITY", "SH000300")
    if sp_p is not None and csi_p is not None:
        diff_pp = sp_p - csi_p
        spreads.append({
            "id": "US_CN_EQ",
            "name": "SP500 - CSI300 Spread",
            "category": "Equity RelVal",
            "value": _r(diff_pp, 2),
            "unit": "pp",
            "secondary": None,
            "secondary_unit": None,
            "legs": ["SP500", "SH000300"],
            "signal": "US LEAD" if diff_pp > 0.5 else ("CN LEAD" if diff_pp < -0.5 else "INLINE"),
        })

    # 8. Rates Key Spreads (from Bonds quotes + YTD Z-score)
    for sym, name, cat in [
        ("2S10S", "UST 2s10s Slope", "Rates Curve"),
        ("3M10Y", "UST 3m10y Slope", "Rates Curve"),
        ("2S5S10S", "UST 2s5s10s Butterfly", "Rates Curvature"),
        ("BEI10Y", "10Y Breakeven Inflation", "Inflation"),
        ("5Y5Y_BEI", "5y5y Forward Inflation", "Inflation"),
    ]:
        q = by_pair.get(("BONDS", sym))
        if not q or _f(q.get("last")) is None:
            continue
        v = float(q["last"])
        cm = curve_by.get(sym) or {}
        if sym in ("2S10S", "3M10Y"):
            sig = "INVERTED" if v < 0 else ("STEEP" if v > 0.75 else "NORMAL")
        elif sym == "2S5S10S":
            sig = "BELLY CHEAP" if v > 0.1 else ("BELLY RICH" if v < -0.1 else "NEUTRAL")
        else:
            sig = "ELEVATED" if v > 2.5 else ("ANCHORED" if v >= 1.8 else "LOW")
        spreads.append({
            "id": sym,
            "name": name,
            "category": cat,
            "value": _r(v * 100.0 if sym in ("2S10S", "3M10Y", "2S5S10S") else v, 1 if sym in ("2S10S", "3M10Y", "2S5S10S") else 2),
            "unit": "bps" if sym in ("2S10S", "3M10Y", "2S5S10S") else "%",
            "secondary": cm.get("zscore_ytd"),
            "secondary_unit": "z(YTD)" if cm.get("zscore_ytd") is not None else None,
            "legs": [sym],
            "signal": sig,
        })

    return spreads


# ----------------------------------------------------------- 3. Macro Regime
def compute_macro_regime(classes, crypto_deriv=None):
    """透明的 Risk-On / Risk-Off 宏观风险情绪合成。

    每项因子显式给出原始值、标准化得分 [-1, +1] 和权重；无黑盒、无缺失补 0。
    """
    by_pair, _ = _quote_map(classes)
    components = []

    def add_comp(name, raw, score, weight, detail):
        clamped = max(-1.0, min(1.0, float(score)))
        components.append({
            "name": name,
            "raw": _r(raw, 3),
            "score": _r(clamped, 3),
            "weight": weight,
            "detail": detail,
        })

    # 1. US Equity Breadth / Momentum (SP500 + NASDAQ avg)
    us_pcts = [
        _f((by_pair.get(("EQUITY", s)) or {}).get("change_pct"))
        for s in ("SP500", "NASDAQ")
    ]
    us_pcts = [x for x in us_pcts if x is not None]
    if us_pcts:
        avg_us = float(np.mean(us_pcts))
        add_comp("US Equities", avg_us, avg_us / 1.5, 0.25, "avg(SP500,NDX) %")

    # 2. China / Asia Equities (CSI300 + HSI)
    asia_pcts = [
        _f((by_pair.get(("EQUITY", s)) or {}).get("change_pct"))
        for s in ("SH000300", "HANGSENG")
    ]
    asia_pcts = [x for x in asia_pcts if x is not None]
    if asia_pcts:
        avg_asia = float(np.mean(asia_pcts))
        add_comp("Asia/CN Equities", avg_asia, avg_asia / 1.5, 0.15, "avg(CSI300,HSI) %")

    # 3. Growth vs Safe-Haven (Copper % - Gold %)
    hg_p = _f((by_pair.get(("COMMODITIES", "HG")) or {}).get("change_pct"))
    gc_p = _f((by_pair.get(("COMMODITIES", "GC")) or {}).get("change_pct"))
    if hg_p is not None and gc_p is not None:
        spread = hg_p - gc_p
        add_comp("Copper vs Gold", spread, spread / 2.0, 0.15, "HG% - GC%")

    # 4. Yield Curve Slope (2S10S)
    s210 = _f((by_pair.get(("BONDS", "2S10S")) or {}).get("last"))
    if s210 is not None:
        add_comp("UST 2s10s", s210, s210 / 0.75, 0.15, "10Y - 2Y (%)")

    # 5. Crypto Beta (BTC 24h %)
    btc_p = _f((by_pair.get(("CRYPTO", "BTC")) or {}).get("change_pct"))
    if btc_p is not None:
        add_comp("BTC Momentum", btc_p, btc_p / 4.0, 0.15, "BTC 24h %")

    # 6. Crypto Perp Funding Sentiment (avg annualized funding)
    deriv_rows = (crypto_deriv or {}).get("rows") or []
    ann_funds = [_f(r.get("funding_ann_pct")) for r in deriv_rows if _f(r.get("funding_ann_pct")) is not None]
    if ann_funds:
        avg_f = float(np.mean(ann_funds))
        # ~10% ann is neutral baseline; >30% bullish/crowded, <0% bearish
        add_comp("Perp Carry", avg_f, (avg_f - 10.0) / 25.0, 0.15, "avg ann funding %")

    if not components:
        return {"score": None, "label": "NO DATA", "n_factors": 0, "components": []}

    w_sum = sum(c["weight"] for c in components)
    composite = sum(c["score"] * c["weight"] for c in components) / w_sum * 100.0
    label = "RISK-ON" if composite >= 20 else ("RISK-OFF" if composite <= -20 else "NEUTRAL")
    return {
        "score": _r(composite, 1),
        "label": label,
        "n_factors": len(components),
        "components": components,
    }


# ----------------------------------------------------------- 4. Symbol Stats
def _downsample(values, max_pts=24):
    n = len(values)
    if n <= max_pts:
        return [round(float(x), 6) for x in values]
    idxs = np.linspace(0, n - 1, max_pts).round().astype(int)
    return [round(float(values[i]), 6) for i in idxs]


def compute_symbol_stats(recent_series):
    """基于 SQLite 历史序列计算单标的 Z-Score、分位数、实现波动率（bps）与 sparkline。"""
    out = {}
    for (cls, sym), pts in (recent_series or {}).items():
        px = np.array([p[1] for p in pts if _f(p[1]) is not None], dtype=float)
        n = int(px.size)
        if n == 0:
            continue
        st = _series_stats(px)
        vol_bps = None
        if n >= 5 and np.all(px > 0):
            rets = np.diff(np.log(px))
            if rets.size >= 4:
                vol_bps = _r(float(np.std(rets, ddof=1)) * 10000.0, 2)
        out["%s:%s" % (cls, sym)] = {
            "asset_class": cls,
            "symbol": sym,
            "n": n,
            "zscore": st["zscore"],
            "pct_rank": st["pct_rank"],
            "vol_bps": vol_bps,
            "sparkline": _downsample(px, 24) if n >= 2 else [],
        }
    return out


# ------------------------------------------------------------ 5. Correlation
def compute_correlation_matrix(recent_series, min_obs=5):
    """跨资产收益率滚动相关性矩阵（pandas Pearson）。

    对所有基准标的按 1 分钟槽对齐取末价后求收益相关性；不足 min_obs 返回 None。
    """
    series_dict = {}
    for cls, sym in CORR_BENCHMARKS:
        pts = (recent_series or {}).get((cls, sym))
        if not pts or len(pts) < min_obs + 1:
            continue
        ts_idx = pd.to_datetime([p[0] for p in pts], utc=True, errors="coerce")
        vals = [p[1] for p in pts]
        s = pd.Series(vals, index=ts_idx).dropna()
        if s.empty:
            continue
        # 按分钟向下对齐取最后价格，使不同刷新周期（5s/10s/15s）能对齐计算同期收益
        s = s.groupby(s.index.floor("min")).last()
        if len(s) >= min_obs + 1:
            series_dict[sym] = s

    if len(series_dict) < 2:
        return {"ok": False, "symbols": list(series_dict.keys()), "matrix": [],
                "n_obs": 0, "min_obs": min_obs,
                "note": "insufficient overlapping history (need >= %d aligned bars)" % (min_obs + 1)}

    df = pd.DataFrame(series_dict).sort_index()
    # 仅使用连续非空观测对（不做跨长空档的伪造前向填充，最多允许 1 个分钟槽对齐）
    rets = df.ffill(limit=1).pct_change().dropna(how="all")
    if len(rets) < min_obs:
        return {"ok": False, "symbols": list(df.columns), "matrix": [],
                "n_obs": int(len(rets)), "min_obs": min_obs,
                "note": "insufficient aligned return observations"}

    syms = list(df.columns)
    corr_df = rets.corr(method="pearson", min_periods=min_obs)
    matrix = []
    for s1 in syms:
        row = []
        for s2 in syms:
            v = corr_df.loc[s1, s2]
            row.append(_r(float(v), 3) if pd.notna(v) and math.isfinite(float(v)) else None)
        matrix.append(row)

    return {
        "ok": True,
        "symbols": syms,
        "matrix": matrix,
        "n_obs": int(len(rets)),
        "min_obs": min_obs,
        "method": "pearson_1m_returns",
    }


# ----------------------------------------------------------- 6. Crypto Quant
def analyze_crypto_quant(crypto_deriv):
    """整理加密永续资金费率、基差与跨所价差排行榜。"""
    if not crypto_deriv or not crypto_deriv.get("rows"):
        return {
            "ok": False,
            "rows": [],
            "top_carry": [],
            "top_dispersion": [],
            "source": (crypto_deriv or {}).get("source"),
            "fetched_at": (crypto_deriv or {}).get("fetched_at"),
            "error": (crypto_deriv or {}).get("error"),
        }
    rows = list(crypto_deriv["rows"])
    carry_sorted = sorted(
        [r for r in rows if _f(r.get("funding_ann_pct")) is not None],
        key=lambda r: abs(r["funding_ann_pct"]),
        reverse=True,
    )
    disp_sorted = sorted(
        [r for r in rows if _f(r.get("dispersion_bps")) is not None],
        key=lambda r: abs(r["dispersion_bps"]),
        reverse=True,
    )
    return {
        "ok": True,
        "rows": rows,
        "top_carry": carry_sorted[:5],
        "top_dispersion": disp_sorted[:5],
        "source": crypto_deriv.get("source"),
        "fetched_at": crypto_deriv.get("fetched_at"),
        "latency_ms": crypto_deriv.get("latency_ms"),
        "error": crypto_deriv.get("error"),
        "partial_error": crypto_deriv.get("partial_error"),
    }


# ------------------------------------------------------------- Top-level API
def build_quant_snapshot(classes, store=None, crypto_deriv=None, curve_history=None):
    """组装完整量化分析快照（嵌入 /api/snapshot 的 quant 字段与 /api/quant）。"""
    ch = curve_history
    if not ch and store is not None:
        ch = store.get_curve_history(days=180)
    if not ch:
        bonds_cls = (classes or {}).get("BONDS") or {}
        ch = bonds_cls.get("curve_history") or []

    curve = analyze_yield_curve(ch)
    spreads = compute_cross_asset_spreads(classes, curve)
    regime = compute_macro_regime(classes, crypto_deriv)
    crypto_q = analyze_crypto_quant(crypto_deriv)

    recent = store.get_recent_prices_by_class(limit_per_symbol=120) if store is not None else {}
    sym_stats = compute_symbol_stats(recent)
    corr = compute_correlation_matrix(recent)

    # 新闻催化剂汇总（若新闻模块已标注 tickers/events）
    news_items = ((classes or {}).get("NEWS") or {}).get("items") or []
    ticker_counts = {}
    event_counts = {}
    sent_counts = {"BULL": 0, "BEAR": 0, "NEUT": 0}
    for it in news_items[:250]:
        for tk in (it.get("tickers") or []):
            ticker_counts[tk] = ticker_counts.get(tk, 0) + 1
        for ev in (it.get("events") or []):
            event_counts[ev] = event_counts.get(ev, 0) + 1
        s_lbl = (it.get("sentiment") or {}).get("label")
        if s_lbl in sent_counts:
            sent_counts[s_lbl] += 1

    news_catalysts = {
        "top_tickers": sorted(ticker_counts.items(), key=lambda kv: kv[1], reverse=True)[:12],
        "top_events": sorted(event_counts.items(), key=lambda kv: kv[1], reverse=True)[:10],
        "sentiment_counts": sent_counts,
        "sample_size": min(len(news_items), 250),
    }

    return {
        "regime": regime,
        "spreads": spreads,
        "yield_curve": curve,
        "crypto_deriv": crypto_q,
        "symbol_stats": sym_stats,
        "correlation": corr,
        "news_catalysts": news_catalysts,
        "storage": store.stats() if store is not None else None,
    }
