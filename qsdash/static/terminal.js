/* QS-DASH 量化终端客户端（v2 Quant Edition）。
   数据经增量 SSE /api/stream 推送（首帧 snapshot + 后续 delta）；断线由 EventSource 自动重连。
   渲染铁律：ok=false 的面板置灰并显示错误原文，绝不把陈旧值当实时值展示；无外部 CDN 请求（AC-D6.6）。
   i18n（AC-D8）：界面文案 en/zh 切换；新闻翻译按需拉取 + 双层缓存 + 额度护栏。 */
(function () {
  'use strict';

  var PAGES = ['OVERVIEW', 'EQUITY', 'FX', 'COMMODITIES', 'BONDS', 'CRYPTO', 'NEWS', 'QUANT', 'BOOK'];
  var CLASS_ORDER = ['EQUITY', 'FX', 'COMMODITIES', 'BONDS', 'CRYPTO'];
  var LANGS = ['en', 'zh'];

  /* 另一语言的类别名，在英文界面下作为暗色副标题出现 */
  var CLASS_ALT = {
    EQUITY: '股票', FX: '外汇', COMMODITIES: '大宗商品',
    BONDS: '债券', CRYPTO: '加密货币', NEWS: '市场情报',
    QUANT: '量化分析', BOOK: '持仓与告警'
  };

  var GROUP_ZH = {
    'US Equity': '美股', 'Global Index': '全球指数', 'China Index': 'A 股指数',
    'FX Spot': '即期', 'Futures (Global)': '国际期货',
    'US Treasury': '美国国债', 'TIPS': '通胀保值国债', 'Curve': '利差',
    'Inflation': '盈亏平衡通胀'
  };
  var CAT_ZH = { CRYPTO: '加密', MACRO: '宏观', GENERAL: '综合' };

  var I18N = {
    en: {
      OVERVIEW: 'OVERVIEW', EQUITY: 'EQUITIES', FX: 'FX', COMMODITIES: 'COMMODITIES',
      BONDS: 'BONDS', CRYPTO: 'CRYPTO', NEWS: 'NEWS', NEWS_PANEL: 'NEWS',
      QUANT: 'QUANT', BOOK: 'BOOK/ALERTS',
      FEED_STATUS: 'FEED STATUS',
      SUB: 'GLOBAL MULTI-ASSET QUANT TERMINAL',
      SYM: 'SYM', NAME: 'NAME', LAST: 'LAST', CHG: 'CHG', CHGP: 'CHG%', OPEN: 'OPEN',
      HIGH: 'HIGH', LOW: 'LOW', VOL: 'VOL', TIME: 'TIME',
      RNGP: 'RNG%', P52W: '52W%', DD52W: 'DD52W', PE: 'P/E',
      SPRD: 'SPRD', FUND: 'FUND/Y', BASIS: 'BASIS', DISP: 'DISP',
      ZSC: 'Z', VOLBP: 'VOL(bp)', SPARK: 'TREND', ZYTD: 'Z(YTD)', CHG1M: '1M',
      L_REGIME: 'REGIME', L_ALERTS: 'ALERTS',
      L_SESSION: 'SESSION', L_UPTIME: 'UPTIME', L_FEEDS: 'FEEDS', L_UPD: 'UPD', L_CLOCK: 'CLOCK',
      CONN_LIVE: 'LIVE', CONN_INIT: 'CONNECTING', CONN_DOWN: 'RECONNECTING',
      L_SRC: 'SRC', L_MODE: 'MODE', S_MODE: 'POLL / DELTA SSE \u00b7 SQLITE + QUANT ANALYTICS',
      S_NOTE: 'data is polled, not tick-level \u2014 see SPEC-DASH \u00a76',
      INSTR: ' INSTR', FEED_DOWN: 'FEED DOWN', STALE: 'STALE',
      SKIPPED: 'skipped', MORE: ' more',
      FOOT: 'SRC {0} \u00b7 HTTP {1} \u00b7 {2} \u00b7 fetched {3} ({4} ago)',
      FOOT_ASOF: ' \u00b7 as_of {0}',
      NO_DATA: 'no data', NO_NEWS: 'no news',
      N_ITEMS: '{0} ITEMS \u00b7 {1}/{2} FEEDS', N_FEEDS: '{0} FEEDS',
      FAILED: 'failed', WAIT: 'waiting for data ...', NO_FEEDS: 'no live feeds',
      ALERT: 'FEED DOWN: {0}  \u2014  panels are greyed; stale values are labelled, not presented as live.',
      MT: 'MT', MT_TIP: 'machine-translated by MyMemory \u2014 may be inaccurate; click to show original',
      ORIG: 'ORIG', ORIG_TIP: 'showing the original headline; click to show the translation',
      XL: 'MT {0}/{1} chars \u00b7 {2}', XL_OFF: 'MT off',
      XL_EXHAUSTED: ' \u00b7 daily quota exhausted',
      TZ_TIP: 'feed supplied no timezone; parsed as UTC',
      Q_PULSE: 'QUANT PULSE', Q_REGIME: 'MACRO REGIME (TRANSPARENT FACTORS)',
      Q_SPREADS: 'CROSS-ASSET SPREADS & STAT-ARB RATIOS',
      Q_CURVE: 'US TREASURY YIELD CURVE & PCA',
      Q_DERIV: 'CRYPTO PERP CARRY, BASIS & CROSS-VENUE DISPERSION',
      Q_CORR: 'CROSS-ASSET ROLLING CORRELATION (1M RETURNS)',
      Q_STATS: 'STATISTICAL SIGNALS & RESEARCH EXPORT',
      Q_CATALYSTS: 'NEWS CATALYSTS & TICKER FLOW',
      B_PORTFOLIO: 'PORTFOLIO MTM PNL & RISK EXPOSURE',
      B_ALERTS: 'QUANT ALERT ENGINE & TRIGGER LOG',
      B_WATCHLIST: 'CUSTOM WATCHLIST OVERRIDES',
      FILTER_PH: 'Filter headlines, tickers (AAPL, BTC) or events (FOMC, INFLATION)...',
      CLEAR: 'CLEAR', ADD: 'ADD', SAVE: 'SAVE', DEL: 'DEL',
      EMPTY_BOOK: 'No positions yet. Add a paper position above to track live MTM PnL & exposure.',
      EMPTY_TRIG: 'No alerts triggered yet.'
    },
    zh: {
      OVERVIEW: '总览', EQUITY: '股票', FX: '外汇', COMMODITIES: '大宗商品',
      BONDS: '债券', CRYPTO: '加密', NEWS: '新闻', NEWS_PANEL: '市场情报',
      QUANT: '量化分析', BOOK: '持仓/告警',
      FEED_STATUS: '数据源状态',
      SUB: '全球多资产量化实时终端',
      SYM: '代码', NAME: '名称', LAST: '最新', CHG: '涨跌', CHGP: '涨跌幅', OPEN: '开盘',
      HIGH: '最高', LOW: '最低', VOL: '成交量', TIME: '时间',
      RNGP: '振幅%', P52W: '52周位', DD52W: '距高点', PE: '市盈率',
      SPRD: '点差', FUND: '年化费率', BASIS: '基差', DISP: '跨所差',
      ZSC: 'Z值', VOLBP: '波动bp', SPARK: '走势', ZYTD: 'YTD Z', CHG1M: '1月变动',
      L_REGIME: '宏观状态', L_ALERTS: '告警',
      L_SESSION: '会话', L_UPTIME: '运行', L_FEEDS: '数据源', L_UPD: '版本', L_CLOCK: '时钟',
      CONN_LIVE: '在线', CONN_INIT: '连接中', CONN_DOWN: '重连中',
      L_SRC: '来源', L_MODE: '模式', S_MODE: '轮询 / 增量 SSE \u00b7 SQLITE + 量化分析',
      S_NOTE: '行情为轮询快照，非逐笔 \u2014 见 SPEC-DASH \u00a76',
      INSTR: ' 标的', FEED_DOWN: '数据中断', STALE: '陈旧',
      SKIPPED: '已跳过', MORE: ' 条',
      FOOT: '来源 {0} \u00b7 HTTP {1} \u00b7 {2} \u00b7 抓取 {3}（{4}前）',
      FOOT_ASOF: ' \u00b7 数据日期 {0}',
      NO_DATA: '无数据', NO_NEWS: '无新闻',
      N_ITEMS: '{0} 条 \u00b7 {1}/{2} 源', N_FEEDS: '{0} 个源',
      FAILED: '失败', WAIT: '等待数据 ...', NO_FEEDS: '暂无可用行情源',
      ALERT: '数据中断：{0}  \u2014  对应面板已置灰；陈旧值均带标注，不会当作实时值展示。',
      MT: '机翻', MT_TIP: '由 MyMemory 机器翻译，可能不准确；点击可看原文',
      ORIG: '原文', ORIG_TIP: '当前显示原文；点击可看译文',
      XL: '机翻额度 {0}/{1} 字符 \u00b7 {2}', XL_OFF: '机翻关闭',
      XL_EXHAUSTED: ' \u00b7 当日额度已用尽',
      TZ_TIP: '该源未提供时区，按 UTC 解析',
      Q_PULSE: '量化脉搏', Q_REGIME: '宏观风险状态（透明因子拆解）',
      Q_SPREADS: '跨资产宏观与统计套利价差',
      Q_CURVE: '美债收益率曲线与三因子 PCA',
      Q_DERIV: '加密永续资金费率、基差与跨所现货价差',
      Q_CORR: '跨资产滚动相关性矩阵（1分钟对齐收益）',
      Q_STATS: '统计异动信号与研究数据导出',
      Q_CATALYSTS: '新闻催化剂与标的提及热度',
      B_PORTFOLIO: '组合实时盯市 PnL 与敞口风控',
      B_ALERTS: '量化规则告警引擎与触发日志',
      B_WATCHLIST: '自定义自选标的扩展',
      FILTER_PH: '按关键词、标的（AAPL/BTC）或宏观事件（FOMC/INFLATION）筛选新闻...',
      CLEAR: '清空', ADD: '添加', SAVE: '保存', DEL: '删除',
      EMPTY_BOOK: '暂无模拟持仓。在上方添加持仓即可实时盯市计算盈亏与资产敞口。',
      EMPTY_TRIG: '暂无已触发的告警记录。'
    }
  };

  var state = {
    snap: null,
    page: 'OVERVIEW',
    lang: 'en',
    prev: {},
    newsFilter: '',
    watchlist: null,
    formMsg: ''
  };

  // ------------------------------------------------------------------ utils
  function el(id) { return document.getElementById(id); }

  function esc(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function t(k) {
    var d = I18N[state.lang] || I18N.en;
    var v = d[k];
    if (v === undefined) { v = I18N.en[k]; }
    return v === undefined ? k : v;
  }

  function sub(k, a, b, c, d2, e2) {
    var s = t(k);
    s = s.replace('{0}', a === undefined ? '' : a).replace('{1}', b === undefined ? '' : b);
    s = s.replace('{2}', c === undefined ? '' : c).replace('{3}', d2 === undefined ? '' : d2);
    s = s.replace('{4}', e2 === undefined ? '' : e2);
    return s;
  }

  function isNum(v) { return typeof v === 'number' && isFinite(v); }

  function decimals(cls, sym, v) {
    if (cls === 'BONDS') return 3;
    if (cls === 'FX') {
      if (/JPY/.test(sym)) return 3;
      if (/CNY|CNH/.test(sym)) return 4;
      return 5;
    }
    if (cls === 'CRYPTO') {
      if (!isNum(v)) return 2;
      if (Math.abs(v) >= 1000) return 2;
      if (Math.abs(v) >= 1) return 3;
      return 5;
    }
    if (cls === 'COMMODITIES') return 3;
    return 2;
  }

  function fmtPx(v, cls, sym) {
    if (!isNum(v)) return '\u2014';
    return v.toFixed(decimals(cls, sym, v));
  }

  function fmtChg(v) {
    if (!isNum(v)) return '\u2014';
    return (v > 0 ? '+' : '') + v.toFixed(4);
  }

  function fmtPct(v) {
    if (!isNum(v)) return '\u2014';
    return (v > 0 ? '+' : '') + v.toFixed(2) + '%';
  }

  function fmtVol(v) {
    if (!isNum(v)) return '\u2014';
    var a = Math.abs(v);
    if (a >= 1e12) return (v / 1e12).toFixed(2) + 'T';
    if (a >= 1e9)  return (v / 1e9).toFixed(2) + 'B';
    if (a >= 1e6)  return (v / 1e6).toFixed(2) + 'M';
    if (a >= 1e3)  return (v / 1e3).toFixed(1) + 'K';
    return v.toFixed(0);
  }

  function fmtUsd(v) {
    if (!isNum(v)) return '\u2014';
    var sign = v < 0 ? '-' : (v > 0 ? '+' : '');
    var a = Math.abs(v);
    if (a >= 1e9) return sign + '$' + (a / 1e9).toFixed(2) + 'B';
    if (a >= 1e6) return sign + '$' + (a / 1e6).toFixed(2) + 'M';
    if (a >= 1e3) return sign + '$' + (a / 1e3).toFixed(2) + 'K';
    return sign + '$' + a.toFixed(2);
  }

  function fmtUsdAbs(v) {
    if (!isNum(v)) return '\u2014';
    var a = Math.abs(v);
    if (a >= 1e9) return '$' + (a / 1e9).toFixed(2) + 'B';
    if (a >= 1e6) return '$' + (a / 1e6).toFixed(2) + 'M';
    if (a >= 1e3) return '$' + (a / 1e3).toFixed(2) + 'K';
    return '$' + a.toFixed(2);
  }

  function dirClass(v) {
    if (!isNum(v) || v === 0) return 'flat';
    return v > 0 ? 'up' : 'down';
  }

  function clockOf(iso) {
    if (!iso) return '\u2014';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso).slice(0, 19);
    return d.toTimeString().slice(0, 8);
  }

  function ageOf(iso) {
    if (!iso) return '\u2014';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '\u2014';
    var s = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
    if (s < 60) return s + 's';
    if (s < 3600) return Math.floor(s / 60) + 'm';
    return Math.floor(s / 3600) + 'h';
  }

  function grp(quotes, key) {
    var out = [], idx = {};
    for (var i = 0; i < quotes.length; i++) {
      var g = quotes[i][key] || '\u2014';
      if (!(g in idx)) { idx[g] = out.length; out.push({ name: g, rows: [] }); }
      out[idx[g]].rows.push(quotes[i]);
    }
    return out;
  }

  function groupLabel(name) {
    if (state.lang === 'zh' && GROUP_ZH[name]) return GROUP_ZH[name];
    return name;
  }

  function catLabel(c) {
    if (state.lang === 'zh' && CAT_ZH[c]) return CAT_ZH[c];
    return c || '';
  }

  function qData() { return (state.snap && state.snap.quant) || {}; }

  function symStat(cls, sym) {
    var m = qData().symbol_stats || {};
    return m[cls + ':' + sym] || null;
  }

  function cryptoDerivMap() {
    var cd = qData().crypto_deriv || {};
    var rows = cd.rows || [], map = {};
    for (var i = 0; i < rows.length; i++) map[rows[i].symbol] = rows[i];
    return map;
  }

  function curveMetricMap() {
    var yc = qData().yield_curve || {};
    var ms = yc.metrics || [], map = {};
    for (var i = 0; i < ms.length; i++) map[ms[i].symbol] = ms[i];
    return map;
  }

  // ------------------------------------------------------------- SVG Charts
  function sparkSvg(pts, w, h) {
    if (!pts || pts.length < 2) return '<span class="dim">\u2014</span>';
    w = w || 54; h = h || 14;
    var mn = pts[0], mx = pts[0], i;
    for (i = 1; i < pts.length; i++) {
      if (pts[i] < mn) mn = pts[i];
      if (pts[i] > mx) mx = pts[i];
    }
    var span = mx - mn;
    var coords = [];
    for (i = 0; i < pts.length; i++) {
      var x = (i / (pts.length - 1) * (w - 2) + 1).toFixed(1);
      var y = span > 0
        ? (h - 2 - ((pts[i] - mn) / span) * (h - 4)).toFixed(1)
        : (h / 2).toFixed(1);
      coords.push(x + ',' + y);
    }
    var up = pts[pts.length - 1] >= pts[0];
    var stroke = pts[pts.length - 1] === pts[0] ? '#7f8fa0' : (up ? '#2ee08a' : '#ff4d5e');
    return '<svg class="spark" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '">' +
      '<polyline fill="none" stroke="' + stroke + '" stroke-width="1.2" points="' + coords.join(' ') + '"/>' +
      '</svg>';
  }

  function yieldCurveSvg(yc) {
    if (!yc || !yc.ok || !yc.snapshots || !yc.snapshots.latest) return '';
    var tenors = yc.tenors || [];
    var latest = yc.snapshots.latest.nominal || {};
    var real = yc.snapshots.latest.real || {};
    var m1 = (yc.snapshots['1m'] && yc.snapshots['1m'].nominal) || null;
    var vals = [], i;
    for (i = 0; i < tenors.length; i++) {
      var tk = tenors[i];
      if (isNum(latest[tk])) vals.push(latest[tk]);
      if (m1 && isNum(m1[tk])) vals.push(m1[tk]);
      if (isNum(real[tk])) vals.push(real[tk]);
    }
    if (vals.length < 2) return '';
    var mn = Math.min.apply(null, vals);
    var mx = Math.max.apply(null, vals);
    var padY = Math.max(0.15, (mx - mn) * 0.12);
    mn -= padY; mx += padY;

    var W = 540, H = 148, PL = 36, PR = 12, PT = 10, PB = 22;
    var pw = W - PL - PR, ph = H - PT - PB;
    function xOf(idx) { return PL + (idx / Math.max(1, tenors.length - 1)) * pw; }
    function yOf(v) { return PT + (1 - (v - mn) / (mx - mn)) * ph; }

    function pathOf(map) {
      var pts = [];
      for (var k = 0; k < tenors.length; k++) {
        var v = map[tenors[k]];
        if (isNum(v)) pts.push(xOf(k).toFixed(1) + ',' + yOf(v).toFixed(1));
      }
      return pts.join(' ');
    }

    var grid = '';
    for (i = 0; i <= 4; i++) {
      var gy = mn + (mx - mn) * (i / 4);
      var yy = yOf(gy).toFixed(1);
      grid += '<line x1="' + PL + '" y1="' + yy + '" x2="' + (W - PR) + '" y2="' + yy +
              '" stroke="#131c26" stroke-width="1"/>' +
              '<text x="' + (PL - 4) + '" y="' + (parseFloat(yy) + 3) +
              '" fill="#5d6d7e" font-size="9" text-anchor="end">' + gy.toFixed(2) + '%</text>';
    }
    for (i = 0; i < tenors.length; i++) {
      var xx = xOf(i).toFixed(1);
      grid += '<text x="' + xx + '" y="' + (H - 6) +
              '" fill="#5d6d7e" font-size="9" text-anchor="middle">' + esc(tenors[i]) + '</text>';
    }

    var lines = '';
    if (m1) {
      var p1m = pathOf(m1);
      if (p1m) lines += '<polyline fill="none" stroke="#5d6d7e" stroke-dasharray="3,3" stroke-width="1.3" points="' + p1m + '"/>';
    }
    var pReal = pathOf(real);
    if (pReal) lines += '<polyline fill="none" stroke="#7fd3ff" stroke-width="1.5" points="' + pReal + '"/>';
    var pNom = pathOf(latest);
    if (pNom) lines += '<polyline fill="none" stroke="#ffa028" stroke-width="2" points="' + pNom + '"/>';

    var dots = '';
    for (i = 0; i < tenors.length; i++) {
      var lv = latest[tenors[i]];
      if (isNum(lv)) {
        dots += '<circle cx="' + xOf(i).toFixed(1) + '" cy="' + yOf(lv).toFixed(1) +
                '" r="2.5" fill="#ffa028"><title>' + esc(tenors[i]) + ': ' + lv.toFixed(2) + '%</title></circle>';
      }
    }

    var pcaHtml = '';
    if (yc.pca && yc.pca.variance_explained_pct) {
      var ve = yc.pca.variance_explained_pct;
      pcaHtml = '<span>PCA(' + yc.pca.n_obs + 'd): L1=' + ve.level_pc1 + '% S2=' +
                ve.slope_pc2 + '% C3=' + ve.curvature_pc3 + '%</span>';
    }

    return '<div class="svg-wrap">' +
      '<svg width="100%" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet">' +
      grid + lines + dots + '</svg>' +
      '<div class="svg-legend">' +
      '<span><i style="background:#ffa028"></i>Nominal (' + esc(yc.as_of || '') + ')</span>' +
      (m1 ? '<span><i style="background:#5d6d7e"></i>1M ago (' + esc(yc.snapshots['1m'].as_of || '') + ')</span>' : '') +
      (pReal ? '<span><i style="background:#7fd3ff"></i>TIPS Real</span>' : '') +
      pcaHtml + '</div></div>';
  }

  // ---------------------------------------------------------------- flashing
  function flashCell(td, key, val) {
    if (!isNum(val)) return;
    var has = Object.prototype.hasOwnProperty.call(state.prev, key);
    var old = state.prev[key];
    state.prev[key] = val;
    if (!has || old === val) return;
    var c = val > old ? 'fu' : 'fd';
    td.classList.remove('fu', 'fd');
    void td.offsetWidth;
    td.classList.add(c);
    window.setTimeout(function () { td.classList.remove(c); }, 800);
  }

  // ----------------------------------------------------------------- columns
  function columnsFor(cls, group) {
    if (cls === 'EQUITY') {
      if (group === 'US Equity') {
        return ['LAST', 'CHG', 'CHGP', 'RNGP', 'P52W', 'DD52W', 'PE', 'VOL', 'SPARK'];
      }
      if (group === 'China Index') {
        return ['LAST', 'CHG', 'CHGP', 'RNGP', 'SPARK', 'TIME'];
      }
      return ['LAST', 'CHG', 'CHGP', 'SPARK'];
    }
    if (cls === 'FX') return ['LAST', 'CHG', 'CHGP', 'ZSC', 'SPARK', 'TIME'];
    if (cls === 'COMMODITIES') return ['LAST', 'CHG', 'CHGP', 'SPRD', 'RNGP', 'SPARK', 'TIME'];
    if (cls === 'BONDS') return ['LAST', 'CHG', 'CHG1M', 'ZYTD'];
    if (cls === 'CRYPTO') return ['LAST', 'CHGP', 'FUND', 'BASIS', 'DISP', 'VOL', 'SPARK'];
    return ['LAST'];
  }

  function cellOf(q, cls, col) {
    var ex = q.extra || {};
    var st = symStat(cls, q.symbol);
    switch (col) {
      case 'LAST': return { t: fmtPx(q.last, cls, q.symbol), c: 'px' };
      case 'CHG':
        if (cls === 'BONDS' && isNum(q.change)) {
          return { t: (q.change > 0 ? '+' : '') + (q.change * 100).toFixed(1) + 'bp',
                   c: dirClass(q.change) };
        }
        return { t: fmtChg(q.change), c: dirClass(q.change) };
      case 'CHGP': return { t: fmtPct(q.change_pct), c: dirClass(q.change_pct) };
      case 'OPEN': return { t: fmtPx(q.open, cls, q.symbol), c: 'dim' };
      case 'HIGH': return { t: fmtPx(q.high, cls, q.symbol), c: 'dim' };
      case 'LOW':  return { t: fmtPx(q.low, cls, q.symbol), c: 'dim' };
      case 'VOL':  return { t: fmtVol(q.volume), c: 'dim' };
      case 'TIME': return { t: clockOf(q.quote_time || q.fetched_at), c: 'dim' };
      case 'RNGP':
        return { t: isNum(ex.range_pct) ? ex.range_pct.toFixed(2) + '%' : '\u2014', c: 'dim' };
      case 'P52W':
        return { t: isNum(ex.pos_52w) ? ex.pos_52w.toFixed(0) + '%' : '\u2014',
                 c: isNum(ex.pos_52w) ? (ex.pos_52w >= 85 ? 'up' : (ex.pos_52w <= 15 ? 'down' : 'dim')) : 'dim' };
      case 'DD52W':
        return { t: isNum(ex.dd_52w) ? ex.dd_52w.toFixed(1) + '%' : '\u2014',
                 c: isNum(ex.dd_52w) && ex.dd_52w <= -15 ? 'down' : 'dim' };
      case 'PE':
        return { t: isNum(ex.pe) && ex.pe > 0 ? ex.pe.toFixed(1) : '\u2014', c: 'dim' };
      case 'SPRD':
        return { t: isNum(ex.spread_bps) ? ex.spread_bps.toFixed(1) + 'bp' : '\u2014',
                 c: isNum(ex.spread_bps) && ex.spread_bps > 10 ? 'down' : 'dim' };
      case 'FUND': {
        var dr = cryptoDerivMap()[q.symbol];
        var fv = dr && dr.funding_ann_pct;
        return { t: isNum(fv) ? (fv > 0 ? '+' : '') + fv.toFixed(1) + '%' : '\u2014',
                 c: isNum(fv) ? (Math.abs(fv) >= 25 ? 'up' : 'dim') : 'dim' };
      }
      case 'BASIS': {
        var dr2 = cryptoDerivMap()[q.symbol];
        var bv = dr2 && dr2.basis_bps;
        return { t: isNum(bv) ? (bv > 0 ? '+' : '') + bv.toFixed(1) + 'bp' : '\u2014',
                 c: dirClass(bv) };
      }
      case 'DISP': {
        var dr3 = cryptoDerivMap()[q.symbol];
        var dv = dr3 && dr3.dispersion_bps;
        return { t: isNum(dv) ? (dv > 0 ? '+' : '') + dv.toFixed(1) + 'bp' : '\u2014',
                 c: isNum(dv) && Math.abs(dv) >= 10 ? 'up' : 'dim' };
      }
      case 'ZSC':
        return { t: st && isNum(st.zscore) ? (st.zscore > 0 ? '+' : '') + st.zscore.toFixed(2) : '\u2014',
                 c: st && isNum(st.zscore) && Math.abs(st.zscore) >= 2 ? 'up' : 'dim' };
      case 'ZYTD': {
        var cm = curveMetricMap()[q.symbol];
        var zv = cm && cm.zscore_ytd;
        return { t: isNum(zv) ? (zv > 0 ? '+' : '') + zv.toFixed(2) : '\u2014',
                 c: isNum(zv) && Math.abs(zv) >= 1.5 ? 'up' : 'dim' };
      }
      case 'CHG1M': {
        var cm2 = curveMetricMap()[q.symbol];
        var c1m = cm2 && cm2.chg_1m_bps;
        return { t: isNum(c1m) ? (c1m > 0 ? '+' : '') + c1m.toFixed(1) + 'bp' : '\u2014',
                 c: dirClass(c1m) };
      }
      case 'SPARK':
        return { html: sparkSvg(st ? st.sparkline : null), c: 'dim' };
      default:
        return { t: '\u2014', c: 'dim' };
    }
  }

  // ------------------------------------------------------------------ panels
  function panelShell(title, alt, metaHtml, footHtml, bodyHtml, dead, wide) {
    return '<section class="panel' + (dead ? ' dead' : '') + (wide ? ' wide' : '') + '">' +
      '<div class="phead"><div class="ptitle">' + esc(title) +
      '<span class="pzh">' + esc(alt || '') + '</span></div>' +
      '<div class="pmeta">' + metaHtml + '</div></div>' +
      bodyHtml +
      '<div class="pfoot">' + footHtml + '</div></section>';
  }

  function footHtml(r, extra) {
    var http = (r.status === null || r.status === undefined) ? '\u2014' : r.status;
    var lat = (r.latency_ms === null || r.latency_ms === undefined)
      ? '\u2014' : r.latency_ms + 'ms';
    var s = sub('FOOT', esc(r.source || '\u2014'), http, lat,
                clockOf(r.fetched_at), r.fetched_at ? ageOf(r.fetched_at) : '\u2014');
    if (r.as_of) s += sub('FOOT_ASOF', esc(r.as_of));
    if (r.stale && r.last_good_age_s !== null && r.last_good_age_s !== undefined) {
      s += ' &middot; <span class="err">' + t('STALE') + ' ' + r.last_good_age_s + 's</span>';
    }
    if (extra) s += ' &middot; ' + extra;
    return s;
  }

  function quoteTable(quotes, cls, group) {
    var cols = columnsFor(cls, group);
    var th = '<thead><tr><th class="l">' + esc(t('SYM')) + '</th><th class="l">' +
             esc(t('NAME')) + '</th>';
    for (var c = 0; c < cols.length; c++) th += '<th>' + esc(t(cols[c])) + '</th>';
    th += '</tr></thead>';

    var tb = '<tbody>';
    for (var i = 0; i < quotes.length; i++) {
      var q = quotes[i];
      tb += '<tr><td class="l"><span class="sym">' + esc(q.symbol) + '</span></td>' +
            '<td class="l"><span class="nm" title="' + esc(q.name) + '">' +
            esc(q.name || '') + '</span></td>';
      for (var k = 0; k < cols.length; k++) {
        var cell = cellOf(q, cls, cols[k]);
        var inner = cell.html !== undefined ? cell.html : cell.t;
        if (cols[k] === 'LAST') {
          tb += '<td class="' + cell.c + '" data-flash="' + esc(cls + ':' + q.symbol) +
                '" data-val="' + esc(q.last) + '">' + inner + '</td>';
        } else {
          tb += '<td class="' + cell.c + '">' + inner + '</td>';
        }
      }
      tb += '</tr>';
    }
    tb += '</tbody>';
    return '<table>' + th + tb + '</table>';
  }

  function skippedNote(r) {
    var s = r.skipped || [];
    if (!s.length) return '';
    var parts = [];
    for (var i = 0; i < s.length && i < 5; i++) {
      parts.push(esc(s[i].symbol) + ' (' + esc(s[i].reason) + ')');
    }
    var more = s.length > 5 ? ' +' + (s.length - 5) + t('MORE') : '';
    return '<div style="padding:2px 8px;color:#5d6d7e;font-size:10px;">' +
      t('SKIPPED') + ': ' + parts.join(', ') + more + '</div>';
  }

  function marketPanels(cls, r) {
    var quotes = r.quotes || [];
    var groups = grp(quotes, 'group');
    var alt = state.lang === 'en' ? (CLASS_ALT[cls] || '') : '';
    var html = '';
    if (cls === 'BONDS' && qData().yield_curve && qData().yield_curve.ok) {
      var yc = qData().yield_curve;
      html += panelShell(t('Q_CURVE'), '', '<span>' + (yc.n_days || 0) + 'd YTD</span>',
        footHtml(r), yieldCurveSvg(yc), !r.ok, state.page === 'BONDS');
    }
    for (var i = 0; i < groups.length; i++) {
      var g = groups[i];
      var title = groups.length > 1 ? t(cls) + ' / ' + groupLabel(g.name) : t(cls);
      var meta = '<span>' + g.rows.length + esc(t('INSTR')) + '</span>';
      if (!r.ok) meta = '<span class="bad">' + esc(t('FEED_DOWN')) + '</span>';
      else if (r.stale) meta = '<span class="stale">' + esc(t('STALE')) + '</span>';
      html += panelShell(title, alt, meta, footHtml(r),
                         quoteTable(g.rows, cls, g.name) + skippedNote(r), !r.ok);
    }
    if (!groups.length) {
      html += panelShell(t(cls), alt,
        '<span class="bad">' + esc(t('FEED_DOWN')) + '</span>', footHtml(r),
        '<div style="padding:10px;color:#ff4d5e;font-size:11px;">' +
        esc(r.error || t('NO_DATA')) + '</div>', true);
    }
    return html;
  }

  // ------------------------------------------------------------ Quant Pulse
  function quantPulsePanel() {
    var q = qData();
    var reg = q.regime || {};
    var spreads = (q.spreads || []).slice(0, 6);
    if (!spreads.length && reg.score === undefined) return '';
    var regCls = reg.label === 'RISK-ON' ? 'up' : (reg.label === 'RISK-OFF' ? 'down' : 'flat');
    var cards = '<div class="qcard"><div class="qlbl">MACRO REGIME</div>' +
      '<div class="qval ' + regCls + '">' + esc(reg.label || '\u2014') + '</div>' +
      '<div class="qsub">score ' + (isNum(reg.score) ? (reg.score > 0 ? '+' : '') + reg.score : '\u2014') +
      ' &middot; ' + (reg.n_factors || 0) + ' factors</div></div>';
    for (var i = 0; i < spreads.length; i++) {
      var s = spreads[i];
      var sec = isNum(s.secondary) ? (' &middot; ' + s.secondary + ' ' + esc(s.secondary_unit || '')) : '';
      cards += '<div class="qcard"><div class="qlbl">' + esc(s.id) + '</div>' +
        '<div class="qval">' + esc(s.value) + ' <span class="dim" style="font-size:10px">' + esc(s.unit || '') + '</span></div>' +
        '<div class="qsub">' + esc(s.signal || '') + sec + '</div></div>';
    }
    var st = q.storage || {};
    var foot = 'SQLite ticks: <b>' + (st.ticks || 0) + '</b> &middot; curve days: <b>' + (st.curve_days || 0) +
      '</b> &middot; <a href="#' + state.lang + '/QUANT" style="color:#ffa028;text-decoration:none">F8 QUANT &rarr;</a>';
    return panelShell(t('Q_PULSE'), state.lang === 'en' ? CLASS_ALT.QUANT : '',
      '<span>' + spreads.length + ' SPREADS</span>', foot, '<div class="qstrip">' + cards + '</div>', false, true);
  }

  // ----------------------------------------------------------- F8 QUANT Page
  function sigTone(sig) {
    if (!sig) return '';
    if (/INVERTED|STRESS|DISCOUNT|DEFENSIVE|HAVEN|ELEVATED|OFF/.test(sig)) return 'neg';
    if (/STEEP|GROWTH|LEAD|OUTPERF|ON|ANCHORED/.test(sig)) return 'pos';
    return 'warn';
  }

  function renderQuantPage() {
    var q = qData();
    var html = '';

    // 1. Macro Regime Factor Decomposition
    var reg = q.regime || {};
    var comps = reg.components || [];
    var regBody = '';
    if (!comps.length) {
      regBody = '<div style="padding:10px;color:#5d6d7e">' + esc(t('NO_DATA')) + '</div>';
    } else {
      for (var i = 0; i < comps.length; i++) {
        var c = comps[i];
        var pct = Math.min(50, Math.abs(c.score || 0) * 50);
        var left = (c.score || 0) >= 0 ? 50 : (50 - pct);
        var col = (c.score || 0) >= 0 ? '#2ee08a' : '#ff4d5e';
        regBody += '<div class="regime-bar-row">' +
          '<span class="sym">' + esc(c.name) + '</span>' +
          '<div class="rbar-track"><div class="rbar-mid"></div>' +
          '<div class="rbar-fill" style="left:' + left.toFixed(1) + '%;width:' + pct.toFixed(1) +
          '%;background:' + col + '"></div></div>' +
          '<span class="' + dirClass(c.score) + '" style="text-align:right">' +
          (isNum(c.score) ? (c.score > 0 ? '+' : '') + c.score.toFixed(2) : '\u2014') + '</span>' +
          '<span class="dim" style="text-align:right">' + esc(c.raw) + ' (' + esc(c.detail) + ')</span></div>';
      }
    }
    var regCls = reg.label === 'RISK-ON' ? 'up' : (reg.label === 'RISK-OFF' ? 'down' : 'flat');
    html += panelShell(t('Q_REGIME'), '',
      '<span class="' + regCls + '">' + esc(reg.label || 'NO DATA') + ' ' +
      (isNum(reg.score) ? '(' + (reg.score > 0 ? '+' : '') + reg.score + ')' : '') + '</span>',
      'Weighted transparent factor composite [-100, +100] &middot; factors=' + (reg.n_factors || 0),
      regBody, false, false);

    // 2. Cross-Asset Spreads & Stat-Arb Ratios
    var sps = q.spreads || [];
    var spBody = '<table><thead><tr><th class="l">ID</th><th class="l">' + esc(t('NAME')) +
      '</th><th>VAL</th><th>AUX</th><th class="l">SIGNAL</th></tr></thead><tbody>';
    for (i = 0; i < sps.length; i++) {
      var s = sps[i];
      spBody += '<tr><td class="l"><span class="sym">' + esc(s.id) + '</span></td>' +
        '<td class="l"><span class="nm">' + esc(s.name) + '</span></td>' +
        '<td class="px">' + esc(s.value) + ' <span class="dim">' + esc(s.unit || '') + '</span></td>' +
        '<td class="dim">' + (isNum(s.secondary) ? esc(s.secondary) + ' ' + esc(s.secondary_unit || '') : '\u2014') + '</td>' +
        '<td class="l"><span class="sig-pill ' + sigTone(s.signal) + '">' + esc(s.signal || '') + '</span></td></tr>';
    }
    spBody += '</tbody></table>';
    html += panelShell(t('Q_SPREADS'), '', '<span>' + sps.length + ' RATIOS</span>',
      'Live derived cross-asset ratios & spreads (missing legs skipped, never zero-filled)',
      sps.length ? spBody : '<div style="padding:10px;color:#5d6d7e">' + esc(t('NO_DATA')) + '</div>', false, false);

    // 3. Yield Curve SVG + YTD Z-Score Table
    var yc = q.yield_curve || {};
    var ycBody = yieldCurveSvg(yc);
    var ym = yc.metrics || [];
    if (ym.length) {
      ycBody += '<table><thead><tr><th class="l">TENOR</th><th>LAST</th><th>1D(bp)</th>' +
        '<th>1M(bp)</th><th>Z(YTD)</th><th>PCTL</th><th>RANGE</th></tr></thead><tbody>';
      for (i = 0; i < ym.length; i++) {
        var m = ym[i];
        ycBody += '<tr><td class="l"><span class="sym">' + esc(m.symbol) + '</span></td>' +
          '<td class="px">' + (isNum(m.last) ? m.last.toFixed(3) : '\u2014') + '</td>' +
          '<td class="' + dirClass(m.chg_1d_bps) + '">' + (isNum(m.chg_1d_bps) ? (m.chg_1d_bps > 0 ? '+' : '') + m.chg_1d_bps.toFixed(1) : '\u2014') + '</td>' +
          '<td class="' + dirClass(m.chg_1m_bps) + '">' + (isNum(m.chg_1m_bps) ? (m.chg_1m_bps > 0 ? '+' : '') + m.chg_1m_bps.toFixed(1) : '\u2014') + '</td>' +
          '<td class="' + (isNum(m.zscore_ytd) && Math.abs(m.zscore_ytd) >= 1.5 ? 'up' : 'dim') + '">' +
          (isNum(m.zscore_ytd) ? (m.zscore_ytd > 0 ? '+' : '') + m.zscore_ytd.toFixed(2) : '\u2014') + '</td>' +
          '<td class="dim">' + (isNum(m.pct_rank_ytd) ? m.pct_rank_ytd.toFixed(0) + '%' : '\u2014') + '</td>' +
          '<td class="dim">' + (isNum(m.ytd_min) && isNum(m.ytd_max) ? m.ytd_min.toFixed(2) + '-' + m.ytd_max.toFixed(2) : '\u2014') + '</td></tr>';
      }
      ycBody += '</tbody></table>';
    }
    html += panelShell(t('Q_CURVE'), '', '<span>' + (yc.n_days || 0) + 'd YTD</span>',
      'US Treasury XML real history &middot; SVD 3-factor PCA on daily bps shifts',
      ycBody || '<div style="padding:10px;color:#5d6d7e">' + esc(t('NO_DATA')) + '</div>', !yc.ok, false);

    // 4. Crypto Derivatives & Cross-Venue Dispersion
    var cd = q.crypto_deriv || {};
    var drs = cd.rows || [];
    var cdBody = '<table><thead><tr><th class="l">SYM</th><th>MARK</th><th>FUND 8H</th>' +
      '<th>CARRY/YR</th><th>BASIS</th><th>OKX DISP</th><th>OI ($)</th></tr></thead><tbody>';
    for (i = 0; i < drs.length; i++) {
      var d = drs[i];
      cdBody += '<tr><td class="l"><span class="sym">' + esc(d.symbol) + '</span></td>' +
        '<td class="px">' + fmtPx(d.mark_price, 'CRYPTO', d.symbol) + '</td>' +
        '<td class="' + dirClass(d.funding_pct_8h) + '">' + (isNum(d.funding_pct_8h) ? d.funding_pct_8h.toFixed(4) + '%' : '\u2014') + '</td>' +
        '<td class="' + dirClass(d.funding_ann_pct) + '">' + (isNum(d.funding_ann_pct) ? (d.funding_ann_pct > 0 ? '+' : '') + d.funding_ann_pct.toFixed(1) + '%' : '\u2014') + '</td>' +
        '<td class="' + dirClass(d.basis_bps) + '">' + (isNum(d.basis_bps) ? (d.basis_bps > 0 ? '+' : '') + d.basis_bps.toFixed(1) + 'bp' : '\u2014') + '</td>' +
        '<td class="' + (isNum(d.dispersion_bps) && Math.abs(d.dispersion_bps) >= 10 ? 'up' : 'dim') + '">' +
        (isNum(d.dispersion_bps) ? (d.dispersion_bps > 0 ? '+' : '') + d.dispersion_bps.toFixed(1) + 'bp' : '\u2014') + '</td>' +
        '<td class="dim">' + fmtUsdAbs(d.oi_usd) + '</td></tr>';
    }
    cdBody += '</tbody></table>';
    html += panelShell(t('Q_DERIV'), '', '<span>' + drs.length + ' PERPS</span>',
      'SRC ' + esc(cd.source || '\u2014') + (cd.error ? ' &middot; <span class="err">' + esc(cd.error) + '</span>' : ''),
      drs.length ? cdBody : '<div style="padding:10px;color:#5d6d7e">' + esc(cd.error || t('NO_DATA')) + '</div>', !cd.ok, false);

    // 5. Rolling Correlation Heatmap
    var corr = q.correlation || {};
    var corrBody = '';
    if (corr.ok && corr.symbols && corr.symbols.length >= 2) {
      corrBody = '<div class="corr-wrap"><table class="corr-tbl"><thead><tr><th></th>';
      for (i = 0; i < corr.symbols.length; i++) corrBody += '<th>' + esc(corr.symbols[i]) + '</th>';
      corrBody += '</tr></thead><tbody>';
      for (i = 0; i < corr.symbols.length; i++) {
        corrBody += '<tr><td class="l"><span class="sym">' + esc(corr.symbols[i]) + '</span></td>';
        for (var j = 0; j < corr.symbols.length; j++) {
          var v = corr.matrix[i][j];
          if (i === j) {
            corrBody += '<td class="c-self">1.00</td>';
          } else if (!isNum(v)) {
            corrBody += '<td class="dim">\u2014</td>';
          } else {
            var alpha = (Math.min(1, Math.abs(v)) * 0.45).toFixed(2);
            var bg = v >= 0 ? 'rgba(46,224,138,' + alpha + ')' : 'rgba(255,77,94,' + alpha + ')';
            corrBody += '<td style="background:' + bg + ';color:#fff">' + v.toFixed(2) + '</td>';
          }
        }
        corrBody += '</tr>';
      }
      corrBody += '</tbody></table></div>';
    } else {
      corrBody = '<div style="padding:10px;color:#5d6d7e">' +
        esc(corr.note || 'Recording live ticks into SQLite; correlation appears once >= 6 aligned 1m bars exist.') + '</div>';
    }
    html += panelShell(t('Q_CORR'), '',
      '<span>n=' + (corr.n_obs || 0) + ' bars</span>',
      'Aligned 1-minute return Pearson correlation (cells with n < ' + (corr.min_obs || 5) + ' stay \u2014)',
      corrBody, false, true);

    // 6. Statistical Signals & Export Bar
    var ss = q.symbol_stats || {};
    var sigRows = [];
    for (var k in ss) {
      if (Object.prototype.hasOwnProperty.call(ss, k) && (isNum(ss[k].zscore) || isNum(ss[k].vol_bps))) {
        sigRows.push(ss[k]);
      }
    }
    sigRows.sort(function (a, b) { return Math.abs(b.zscore || 0) - Math.abs(a.zscore || 0); });
    var stBody = '';
    if (sigRows.length) {
      stBody += '<table><thead><tr><th class="l">SYM</th><th class="l">CLASS</th><th>N</th>' +
        '<th>Z-SCORE</th><th>PCTL</th><th>VOL(bp)</th><th>TREND</th></tr></thead><tbody>';
      for (i = 0; i < Math.min(15, sigRows.length); i++) {
        var r = sigRows[i];
        stBody += '<tr><td class="l"><span class="sym">' + esc(r.symbol) + '</span></td>' +
          '<td class="l dim">' + esc(r.asset_class) + '</td>' +
          '<td class="dim">' + r.n + '</td>' +
          '<td class="' + dirClass(r.zscore) + '">' + (isNum(r.zscore) ? (r.zscore > 0 ? '+' : '') + r.zscore.toFixed(2) : '\u2014') + '</td>' +
          '<td class="dim">' + (isNum(r.pct_rank) ? r.pct_rank.toFixed(0) + '%' : '\u2014') + '</td>' +
          '<td class="dim">' + (isNum(r.vol_bps) ? r.vol_bps.toFixed(1) : '\u2014') + '</td>' +
          '<td>' + sparkSvg(r.sparkline) + '</td></tr>';
      }
      stBody += '</tbody></table>';
    } else {
      stBody = '<div style="padding:8px;color:#5d6d7e">Collecting SQLite tick history (z-score requires n &ge; 5)...</div>';
    }
    var stor = q.storage || {};
    stBody += '<div class="export-row"><span>CSV / API Export:</span>' +
      '<a href="/api/export.csv?limit=5000" download>ALL TICKS CSV</a>' +
      '<a href="/api/export.csv?asset_class=CRYPTO&limit=5000" download>CRYPTO CSV</a>' +
      '<a href="/api/export.csv?asset_class=EQUITY&limit=5000" download>EQUITY CSV</a>' +
      '<a href="/api/export.csv?asset_class=FX&limit=5000" download>FX CSV</a>' +
      '<a href="/api/history?type=curve&limit=200" target="_blank">CURVE JSON</a>' +
      '<a href="/api/quant" target="_blank">QUANT JSON</a>' +
      '<span>SQLite: ' + (stor.ticks || 0) + ' ticks / ' + (stor.symbols || 0) + ' syms</span></div>';
    html += panelShell(t('Q_STATS'), '', '<span>' + sigRows.length + ' ACTIVE</span>',
      'Programmatic endpoints: /api/quant &middot; /api/history &middot; /api/export.csv',
      stBody, false, true);

    return html;
  }

  // ------------------------------------------------------- F9 BOOK / ALERTS
  function renderBookPage() {
    var pf = (state.snap && state.snap.portfolio) || { positions: [], summary: {}, exposure_by_class: {} };
    var al = (state.snap && state.snap.alerts) || { rules: [], triggered: [] };
    var ps = pf.summary || {};
    var html = '';

    // 1. Portfolio Panel
    var pCards = '<div class="qstrip">' +
      '<div class="qcard"><div class="qlbl">GROSS EXP</div><div class="qval">' + fmtUsdAbs(ps.gross_exposure) + '</div></div>' +
      '<div class="qcard"><div class="qlbl">NET EXP</div><div class="qval ' + dirClass(ps.net_exposure) + '">' + fmtUsd(ps.net_exposure) + '</div></div>' +
      '<div class="qcard"><div class="qlbl">UNREALIZED PNL</div><div class="qval ' + dirClass(ps.unrealized_pnl) + '">' + fmtUsd(ps.unrealized_pnl) + '</div></div>' +
      '<div class="qcard"><div class="qlbl">DAY PNL</div><div class="qval ' + dirClass(ps.day_pnl) + '">' + fmtUsd(ps.day_pnl) + '</div></div>' +
      '<div class="qcard"><div class="qlbl">CONCENTRATION (HHI)</div><div class="qval">' + (isNum(ps.concentration_hhi) ? ps.concentration_hhi.toFixed(3) : '\u2014') + '</div></div>' +
      '</div>';

    var pForm = '<form class="qform" id="form-pos">' +
      '<input name="symbol" placeholder="SYM (BTC, AAPL)" style="width:110px" required>' +
      '<select name="side"><option value="LONG">LONG</option><option value="SHORT">SHORT</option></select>' +
      '<input name="qty" type="number" step="any" placeholder="QTY" style="width:90px" required>' +
      '<input name="entry_price" type="number" step="any" placeholder="ENTRY PX" style="width:105px" required>' +
      '<input name="note" placeholder="NOTE" style="width:130px">' +
      '<button type="submit" class="qbtn">' + esc(t('ADD')) + '</button>' +
      (state.formMsg ? '<span class="qmsg">' + esc(state.formMsg) + '</span>' : '') +
      '</form>';

    var posRows = pf.positions || [];
    var pTbl = '';
    if (!posRows.length) {
      pTbl = '<div style="padding:10px;color:#5d6d7e">' + esc(t('EMPTY_BOOK')) + '</div>';
    } else {
      pTbl = '<table><thead><tr><th class="l">SYM</th><th class="l">SIDE</th><th>QTY</th>' +
        '<th>ENTRY</th><th>MARK</th><th>NOTIONAL</th><th>UPNL</th><th>UPNL%</th><th>WT%</th><th></th></tr></thead><tbody>';
      for (var i = 0; i < posRows.length; i++) {
        var r = posRows[i];
        pTbl += '<tr><td class="l"><span class="sym">' + esc(r.symbol) + '</span> <span class="dim">' + esc(r.asset_class || '') + '</span></td>' +
          '<td class="l ' + (r.side === 'LONG' ? 'up' : 'down') + '">' + esc(r.side) + '</td>' +
          '<td class="dim">' + esc(r.qty) + '</td>' +
          '<td class="dim">' + esc(r.entry_price) + '</td>' +
          '<td class="px">' + (isNum(r.mark_price) ? r.mark_price : '<span class="err">unpriced</span>') + '</td>' +
          '<td class="dim">' + fmtUsdAbs(r.notional) + '</td>' +
          '<td class="' + dirClass(r.unrealized_pnl) + '">' + fmtUsd(r.unrealized_pnl) + '</td>' +
          '<td class="' + dirClass(r.unrealized_pnl_pct) + '">' + fmtPct(r.unrealized_pnl_pct) + '</td>' +
          '<td class="dim">' + (isNum(r.weight_pct) ? r.weight_pct.toFixed(1) + '%' : '\u2014') + '</td>' +
          '<td><button class="qbtn-del" data-del-pos="' + esc(r.id) + '">' + esc(t('DEL')) + '</button></td></tr>';
      }
      pTbl += '</tbody></table>';
    }
    html += panelShell(t('B_PORTFOLIO'), '',
      '<span>' + (ps.count || 0) + ' POSITIONS</span>',
      'Local paper book only (no broker execution). Unpriced symbols stay \u2014.',
      pCards + pForm + pTbl, false, true);

    // 2. Alerts Panel
    var aForm = '<form class="qform" id="form-alert">' +
      '<select name="type">' +
      '<option value="price_above">price_above</option>' +
      '<option value="price_below">price_below</option>' +
      '<option value="pct_move_abs">pct_move_abs</option>' +
      '<option value="spread_above">spread_above</option>' +
      '<option value="spread_below">spread_below</option>' +
      '<option value="zscore_abs">zscore_abs</option>' +
      '<option value="funding_ann_abs">funding_ann_abs</option>' +
      '<option value="dispersion_bps">dispersion_bps</option>' +
      '<option value="news_keyword">news_keyword</option>' +
      '</select>' +
      '<input name="target" placeholder="TARGET (BTC, 2S10S, *)" style="width:140px" required>' +
      '<input name="threshold" type="number" step="any" placeholder="THRESHOLD" style="width:100px">' +
      '<input name="name" placeholder="RULE LABEL" style="width:150px">' +
      '<button type="submit" class="qbtn">' + esc(t('ADD')) + '</button>' +
      '<button type="button" class="qbtn" id="btn-clear-alerts">' + esc(t('CLEAR')) + ' LOG</button>' +
      '</form>';

    var trig = al.triggered || [];
    var trigHtml = '<div style="max-height:160px;overflow-y:auto;border-bottom:1px solid #1a2531">';
    if (!trig.length) {
      trigHtml += '<div style="padding:8px;color:#5d6d7e">' + esc(t('EMPTY_TRIG')) + '</div>';
    } else {
      for (i = 0; i < trig.length; i++) {
        var ev = trig[i];
        trigHtml += '<div style="padding:3px 8px;border-bottom:1px solid #131c26;font-size:11px">' +
          '<span class="dim">' + esc(clockOf(ev.ts)) + '</span> ' +
          '<span class="sig-pill warn">' + esc(ev.type) + '</span> ' +
          '<span class="px">' + esc(ev.message) + '</span></div>';
      }
    }
    trigHtml += '</div>';

    var rules = al.rules || [];
    var rTbl = '<table><thead><tr><th class="l">RULE</th><th class="l">TYPE</th><th class="l">TARGET</th>' +
      '<th>THR</th><th>CD(s)</th><th></th></tr></thead><tbody>';
    for (i = 0; i < rules.length; i++) {
      var rl = rules[i];
      rTbl += '<tr><td class="l">' + esc(rl.name) + '</td>' +
        '<td class="l dim">' + esc(rl.type) + '</td>' +
        '<td class="l sym">' + esc(rl.target) + '</td>' +
        '<td class="px">' + (rl.threshold !== null && rl.threshold !== undefined ? esc(rl.threshold) : '\u2014') + '</td>' +
        '<td class="dim">' + esc(rl.cooldown_s) + '</td>' +
        '<td><button class="qbtn-del" data-del-rule="' + esc(rl.id) + '">' + esc(t('DEL')) + '</button></td></tr>';
    }
    rTbl += '</tbody></table>';
    html += panelShell(t('B_ALERTS'), '',
      '<span>' + rules.length + ' RULES &middot; ' + trig.length + ' FIRED</span>',
      'Rules persisted to data/alerts.json &middot; API: GET/POST/DELETE /api/alerts',
      aForm + trigHtml + rTbl, false, true);

    // 3. Watchlist Editor
    var ov = (state.watchlist && state.watchlist.overrides) || {};
    var wForm = '<form class="qform" id="form-watch">' +
      '<label class="dim">US:</label><input name="us_equity" value="' + esc((ov.us_equity || []).join(', ')) + '" placeholder="amd, nflx, spy" style="width:150px">' +
      '<label class="dim">CN:</label><input name="cn_equity" value="' + esc((ov.cn_equity || []).join(', ')) + '" placeholder="sh600519" style="width:120px">' +
      '<label class="dim">CRYPTO:</label><input name="crypto" value="' + esc((ov.crypto || []).join(', ')) + '" placeholder="ARB, OP, PEPE" style="width:150px">' +
      '<button type="submit" class="qbtn">' + esc(t('SAVE')) + '</button>' +
      '</form>';
    html += panelShell(t('B_WATCHLIST'), '', '<span>EXTENDS DEFAULT UNIVERSE</span>',
      'Saved to data/watchlist.json; picked up on next refresh cycle', wForm, false, true);

    return html;
  }

  // ------------------------------------------------------------------- News
  function filterNewsItems(items) {
    var q = (state.newsFilter || '').trim().toLowerCase();
    if (!q) return items;
    var out = [];
    for (var i = 0; i < items.length; i++) {
      var n = items[i];
      var hay = ((n.title || '') + ' ' + (n.summary || '') + ' ' + (n.source || '') + ' ' +
                 (n.tickers || []).join(' ') + ' ' + (n.events || []).join(' ') + ' ' +
                 ((n.sentiment && n.sentiment.label) || '')).toLowerCase();
      if (hay.indexOf(q) >= 0) out.push(n);
    }
    return out;
  }

  function newsPanel(r, limit, withControls) {
    var allItems = r.items || [];
    var filtered = withControls ? filterNewsItems(allItems) : allItems;
    var items = filtered.slice(0, limit || 60);
    var body = '';

    if (withControls) {
      var cat = qData().news_catalysts || {};
      var chips = '';
      var tks = (cat.top_tickers || []).slice(0, 8);
      for (var ti = 0; ti < tks.length; ti++) {
        var tk = tks[ti][0];
        chips += '<span class="chip' + (state.newsFilter.toUpperCase() === tk ? ' active' : '') +
                 '" data-nf="' + esc(tk) + '">' + esc(tk) + ':' + tks[ti][1] + '</span>';
      }
      var evs = (cat.top_events || []).slice(0, 6);
      for (var ei = 0; ei < evs.length; ei++) {
        var ev = evs[ei][0];
        chips += '<span class="chip' + (state.newsFilter.toUpperCase() === ev ? ' active' : '') +
                 '" data-nf="' + esc(ev) + '">' + esc(ev) + ':' + evs[ei][1] + '</span>';
      }
      body += '<div class="news-bar">' +
        '<input id="news-filter" type="text" value="' + esc(state.newsFilter) +
        '" placeholder="' + esc(t('FILTER_PH')) + '" style="flex:1 1 240px">' +
        (state.newsFilter ? '<button type="button" class="qbtn" id="news-filter-clr">' + esc(t('CLEAR')) + '</button>' : '') +
        chips + '</div>';
    }

    if (!items.length) {
      body += '<div style="padding:10px;color:#ff4d5e;font-size:11px;">' +
              esc(r.error || t('NO_NEWS')) + '</div>';
    } else {
      body += '<ul class="news-list">';
      for (var i = 0; i < items.length; i++) {
        var n = items[i];
        var tMark = n.tz_assumed ? '~' : '';
        var tTitle = n.tz_assumed ? ' title="' + esc(t('TZ_TIP')) + '"' : '';
        var title = n.title || '';
        var tagsHtml = '';
        var nTks = n.tickers || [];
        for (var k = 0; k < nTks.length && k < 3; k++) {
          tagsHtml += '<span class="tk-tag" data-nf="' + esc(nTks[k]) + '">' + esc(nTks[k]) + '</span>';
        }
        var nEvs = n.events || [];
        for (var e = 0; e < nEvs.length && e < 2; e++) {
          tagsHtml += '<span class="ev-tag" data-nf="' + esc(nEvs[e]) + '">' + esc(nEvs[e]) + '</span>';
        }
        var sLbl = n.sentiment && n.sentiment.label;
        if (sLbl === 'BULL' || sLbl === 'BEAR') {
          tagsHtml += '<span class="sent-tag ' + sLbl + '" title="lexicon sentiment">' + sLbl + '</span>';
        }
        body += '<li><div>' +
          '<span class="news-time"' + tTitle + '>' + tMark + clockOf(n.ts) + '</span>' +
          '<span class="news-src">' + esc(n.source || n.feed) + '</span>' +
          '<span class="news-title"><a href="' + esc(n.link) + '" target="_blank" rel="noopener"' +
          ' data-src="' + esc(title) + '">' + esc(title) + '</a>' +
          '<span class="mt-badge hidden" title="' + esc(t('MT_TIP')) + '">' +
          esc(t('MT')) + '</span></span>' +
          tagsHtml +
          '<span class="news-cat ' + esc(n.category) + '">' + esc(catLabel(n.category)) + '</span>' +
          '</div>' +
          (n.summary ? '<div class="news-sum">' + esc(n.summary) + '</div>' : '') +
          '</li>';
      }
      body += '</ul>';
    }
    var feeds = r.feeds || [];
    var bad = [];
    for (var f = 0; f < feeds.length; f++) if (!feeds[f].ok) bad.push(feeds[f]);
    var meta = '<span>' + sub('N_ITEMS', filtered.length,
                              feeds.length - bad.length, feeds.length) + '</span>';
    var fh = footHtml(r, '<span class="xl-budget" data-xl="1"></span>');
    if (bad.length) {
      var names = [];
      for (var b = 0; b < bad.length; b++) {
        names.push(esc(bad[b].feed) + ' (' + esc(bad[b].error) + ')');
      }
      fh += '<br><span class="err">' + t('FAILED') + ': ' + names.join(', ') + '</span>';
    }
    return panelShell(t('NEWS_PANEL'), state.lang === 'en' ? CLASS_ALT.NEWS : '',
                      meta, fh, body, !r.ok, withControls);
  }

  // ------------------------------------------------------- 翻译（AC-D8.3-D8.7）
  var xlate = { map: {}, budget: null, inflight: false };

  function visibleNewsAnchors() {
    return document.querySelectorAll('.news-title a[data-src]');
  }

  function requestTranslations() {
    if (state.lang !== 'zh') return;
    var nodes = visibleNewsAnchors();
    var want = [], seen = {}, i;
    for (i = 0; i < nodes.length && want.length < 30; i++) {
      var src = nodes[i].getAttribute('data-src');
      if (!src || xlate.map[src] !== undefined || seen[src]) continue;
      seen[src] = 1;
      want.push(src);
    }
    if (!want.length || xlate.inflight) { applyTranslations(); return; }

    xlate.inflight = true;
    fetch('/api/translate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to: 'zh', texts: want })
    }).then(function (r) { return r.json(); })
      .then(function (d) {
        xlate.inflight = false;
        if (!d || !d.ok) { applyTranslations(); return; }
        if (d.budget) xlate.budget = d.budget;
        var res = d.results || [];
        for (var j = 0; j < res.length; j++) {
          if (want[j] !== undefined) xlate.map[want[j]] = res[j];
        }
        applyTranslations();
        renderBudget();
      })
      .catch(function () { xlate.inflight = false; applyTranslations(); });
  }

  function applyTranslations() {
    var nodes = visibleNewsAnchors(), i;
    for (i = 0; i < nodes.length; i++) {
      var a = nodes[i];
      var src = a.getAttribute('data-src') || '';
      var r = xlate.map[src];
      var wantZh = state.lang === 'zh';
      if (!wantZh || !r || !r.ok) {
        a.textContent = src;
        a.classList.remove('mt-shown');
        a.removeAttribute('data-mt');
        if (r && !r.ok && r.error) a.setAttribute('data-err', r.error);
      } else if (a.getAttribute('data-show') === 'orig') {
        a.textContent = src;
        a.classList.remove('mt-shown');
      } else {
        a.textContent = r.text;
        a.classList.add('mt-shown');
        a.setAttribute('data-mt', '1');
        a.removeAttribute('data-err');
      }
    }
    renderMarks();
  }

  function renderMarks() {
    var badges = document.querySelectorAll('.mt-badge'), i;
    for (i = 0; i < badges.length; i++) {
      var b = badges[i];
      var wrap = b.parentNode;
      var a = wrap ? wrap.querySelector('a[data-src]') : null;
      if (!a) { b.classList.add('hidden'); continue; }
      var r = xlate.map[a.getAttribute('data-src') || ''];
      if (state.lang === 'zh' && r && r.ok) {
        var showingOrig = a.getAttribute('data-show') === 'orig';
        b.classList.remove('hidden');
        b.textContent = showingOrig ? t('ORIG') : t('MT');
        b.setAttribute('title', showingOrig ? t('ORIG_TIP') : t('MT_TIP'));
      } else {
        b.classList.add('hidden');
      }
    }
  }

  function renderBudget() {
    var nodes = document.querySelectorAll('[data-xl]'), i;
    if (!nodes.length) return;
    var txt = t('XL_OFF');
    if (state.lang === 'zh' && xlate.budget) {
      txt = sub('XL', xlate.budget.used, xlate.budget.limit, xlate.budget.provider) +
            (xlate.budget.exhausted ? t('XL_EXHAUSTED') : '');
    }
    for (i = 0; i < nodes.length; i++) nodes[i].textContent = txt;
  }

  // ------------------------------------------------------------------ render
  function isUserTyping() {
    var ae = document.activeElement;
    return ae && /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName);
  }

  function renderGrid() {
    var snap = state.snap;
    var grid = el('grid');
    if (!snap || !snap.classes) { grid.innerHTML = ''; return; }
    var html = '';
    var page = state.page;
    var i;

    if (page === 'OVERVIEW') {
      html += quantPulsePanel();
      for (i = 0; i < CLASS_ORDER.length; i++) {
        var r = snap.classes[CLASS_ORDER[i]];
        if (r) html += marketPanels(CLASS_ORDER[i], r);
      }
      if (snap.classes.NEWS) html += newsPanel(snap.classes.NEWS, 25, false);
    } else if (page === 'NEWS') {
      var nr = snap.classes.NEWS;
      if (nr) {
        var feeds = nr.feeds || [], parts = [];
        for (i = 0; i < feeds.length; i++) {
          parts.push('<span class="' + (feeds[i].ok ? '' : 'err') + '">' +
                     esc(feeds[i].feed) + ':' + (feeds[i].count || 0) + '</span>');
        }
        html += panelShell(t('FEED_STATUS'), '', '<span>' + sub('N_FEEDS', feeds.length) + '</span>',
                           parts.join(' &middot; '), '', false, true);
        html += newsPanel(nr, 400, true);
      }
    } else if (page === 'QUANT') {
      html += renderQuantPage();
    } else if (page === 'BOOK') {
      html += renderBookPage();
    } else {
      var rr = snap.classes[page];
      if (rr) html += marketPanels(page, rr);
      if (snap.classes.NEWS) html += newsPanel(snap.classes.NEWS, 25, false);
    }
    grid.innerHTML = html;
    applyFlashes();
    applyTranslations();
    renderBudget();
    requestTranslations();
  }

  function applyFlashes() {
    var cells = document.querySelectorAll('td[data-flash]');
    for (var i = 0; i < cells.length; i++) {
      flashCell(cells[i], cells[i].getAttribute('data-flash'),
                parseFloat(cells[i].getAttribute('data-val')));
    }
  }

  function renderTape() {
    var snap = state.snap;
    var track = el('tape-track');
    if (!snap || !snap.classes) {
      track.innerHTML = '<span class="tape-empty">' + esc(t('WAIT')) + '</span>';
      return;
    }
    var out = '';
    for (var i = 0; i < CLASS_ORDER.length; i++) {
      var cls = CLASS_ORDER[i];
      var r = snap.classes[cls];
      if (!r || !r.ok) continue;
      var qs = r.quotes || [];
      for (var j = 0; j < qs.length; j++) {
        var q = qs[j];
        out += '<span class="tape-item"><span class="t-sym">' + esc(q.symbol) + '</span>' +
               '<span class="t-px">' + fmtPx(q.last, cls, q.symbol) + '</span>' +
               '<span class="' + dirClass(q.change_pct) + '">' + fmtPct(q.change_pct) +
               '</span></span>';
      }
    }
    if (!out) out = '<span class="tape-empty">' + esc(t('NO_FEEDS')) + '</span>';
    track.innerHTML = out + out;
  }

  function renderChrome() {
    var snap = state.snap;
    if (!snap) return;
    var s = snap.summary || {};
    el('m-session').textContent = (snap.started_at || '').replace('T', ' ').slice(5, 19);
    el('m-feeds').textContent = (s.classes_ok || 0) + '/' + (s.classes_total || 0);
    el('m-upd').textContent = (snap.version || 0);

    var reg = (snap.quant && snap.quant.regime) || {};
    var mr = el('m-regime');
    if (mr) {
      mr.textContent = reg.label ? (reg.label + (isNum(reg.score) ? ' ' + (reg.score > 0 ? '+' : '') + reg.score : '')) : '\u2014';
      mr.className = reg.label === 'RISK-ON' ? 'regime-on'
        : (reg.label === 'RISK-OFF' ? 'regime-off' : 'regime-neu');
    }
    var ma = el('m-alerts');
    if (ma) {
      var tc = (snap.alerts && snap.alerts.triggered_count) || 0;
      ma.textContent = String(tc);
      ma.className = tc > 0 ? 'alert-hot' : '';
    }

    var srcs = [];
    for (var i = 0; i < CLASS_ORDER.length; i++) {
      var r = snap.classes[CLASS_ORDER[i]];
      if (r && r.source && srcs.indexOf(r.source) < 0) srcs.push(r.source);
    }
    if (snap.classes.NEWS && snap.classes.NEWS.source) srcs.push(snap.classes.NEWS.source);
    el('s-src').textContent = srcs.join(' / ') || '\u2014';

    var degraded = s.degraded || [];
    var alert = el('alert');
    if (degraded.length) {
      alert.classList.remove('hidden');
      alert.textContent = sub('ALERT', degraded.join(', '));
    } else {
      alert.classList.add('hidden');
    }
  }

  var STATIC_LABELS = [
    ['b-sub', 'SUB'], ['l-regime', 'L_REGIME'], ['l-alerts', 'L_ALERTS'],
    ['l-session', 'L_SESSION'], ['l-uptime', 'L_UPTIME'],
    ['l-feeds', 'L_FEEDS'], ['l-upd', 'L_UPD'], ['l-clock', 'L_CLOCK'],
    ['l-src', 'L_SRC'], ['l-mode', 'L_MODE']
  ];

  function applyLabels() {
    for (var i = 0; i < STATIC_LABELS.length; i++) {
      var node = el(STATIC_LABELS[i][0]);
      if (node) node.textContent = t(STATIC_LABELS[i][1]);
    }
    var mode = el('s-mode');
    if (mode) mode.textContent = t('S_MODE');
    var note = el('s-note');
    if (note) note.textContent = t('S_NOTE');
  }

  function renderFnBar() {
    var bar = el('fnbar');
    bar.innerHTML = '';
    for (var i = 0; i < PAGES.length; i++) {
      var b = document.createElement('button');
      b.className = 'fn' + (PAGES[i] === state.page ? ' active' : '');
      b.setAttribute('data-key', PAGES[i]);
      b.innerHTML = '<span class="fkey">F' + (i + 1) + '</span>' + esc(t(PAGES[i]));
      b.addEventListener('click', (function (key) {
        return function () { setPage(key); };
      })(PAGES[i]));
      bar.appendChild(b);
    }
  }

  function renderLangTog() {
    var box = el('lang-tog');
    box.innerHTML = '';
    for (var i = 0; i < LANGS.length; i++) {
      var b = document.createElement('button');
      b.className = LANGS[i] === state.lang ? 'active' : '';
      b.textContent = LANGS[i] === 'zh' ? '\u4e2d\u6587' : 'EN';
      b.setAttribute('title', LANGS[i] === 'zh' ? '\u4e2d\u6587\u754c\u9762' : 'English UI');
      b.addEventListener('click', (function (l) {
        return function () { setLang(l); };
      })(LANGS[i]));
      box.appendChild(b);
    }
  }

  function setPage(key, skipHash) {
    state.page = key;
    var btns = document.querySelectorAll('.fn');
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle('active', btns[i].getAttribute('data-key') === key);
    }
    if (!skipHash) writeHash();
    if (key === 'BOOK' && !state.watchlist) {
      fetch('/api/watchlist').then(function (r) { return r.json(); })
        .then(function (d) { state.watchlist = d; if (state.page === 'BOOK') renderGrid(); })
        .catch(function () {});
    }
    renderGrid();
  }

  function setLang(l) {
    if (LANGS.indexOf(l) < 0 || l === state.lang) return;
    state.lang = l;
    try { window.localStorage.setItem('qsdash.lang', l); } catch (e) { /* 隐私模式 */ }
    document.documentElement.setAttribute('lang', l === 'zh' ? 'zh-CN' : 'en');
    applyLabels();
    renderLangTog();
    renderFnBar();
    renderChrome();
    renderTape();
    writeHash();
    renderGrid();
  }

  function writeHash() {
    var want = '#' + state.lang + '/' + state.page;
    if (window.location.hash !== want) window.location.hash = want;
  }

  function setConn(status) {
    var c = el('conn');
    c.className = 'conn conn-' + status;
    c.textContent = status === 'live' ? t('CONN_LIVE')
      : (status === 'down' ? t('CONN_DOWN') : t('CONN_INIT'));
  }

  // --------------------------------------------------------------- transport
  function apply(snap) {
    state.snap = snap;
    renderChrome();
    renderTape();
    if (!isUserTyping()) renderGrid();
  }

  function applyDelta(delta) {
    if (!state.snap) return;
    state.snap.version = delta.version;
    state.snap.server_time = delta.server_time;
    state.snap.summary = delta.summary || state.snap.summary;
    state.snap.quant = delta.quant || state.snap.quant;
    state.snap.alerts = delta.alerts || state.snap.alerts;
    state.snap.portfolio = delta.portfolio || state.snap.portfolio;
    var ch = delta.changed || {};
    var marketChanged = false;
    for (var cls in ch) {
      if (Object.prototype.hasOwnProperty.call(ch, cls)) {
        state.snap.classes[cls] = ch[cls];
        if (cls !== 'NEWS') marketChanged = true;
      }
    }
    renderChrome();
    if (marketChanged) renderTape();
    if (!isUserTyping()) {
      // 在 NEWS 页且仅行情变动时不重绘新闻 DOM，避免打断阅读或重复触发滚动重置
      if (state.page === 'NEWS' && !ch.NEWS) return;
      renderGrid();
    }
  }

  function splitCsv(s) {
    return (s || '').split(',').map(function (x) { return x.trim(); }).filter(Boolean);
  }

  function boot() {
    var fromHash = null, fromPage = null;
    var raw = (window.location.hash || '').replace(/^#/, '');
    var parts = raw.split('/').filter(Boolean);
    for (var i = 0; i < parts.length; i++) {
      var low = parts[i].toLowerCase();
      if (LANGS.indexOf(low) >= 0) { fromHash = low; continue; }
      var up = parts[i].toUpperCase();
      if (PAGES.indexOf(up) >= 0) { fromPage = up; }
    }
    var stored = null;
    try { stored = window.localStorage.getItem('qsdash.lang'); } catch (e) { stored = null; }
    var nav = (navigator.language || 'en').toLowerCase();
    state.lang = fromHash || (LANGS.indexOf(stored) >= 0 ? stored : null)
      || (nav.indexOf('zh') === 0 ? 'zh' : 'en');
    if (fromPage) state.page = fromPage;
    document.documentElement.setAttribute('lang', state.lang === 'zh' ? 'zh-CN' : 'en');

    applyLabels();
    renderLangTog();
    renderFnBar();

    var kva = el('kv-alerts');
    if (kva) kva.addEventListener('click', function () { setPage('BOOK'); });

    fetch('/api/i18n').then(function (r) { return r.json(); })
      .then(function (d) { if (d && d.budget) { xlate.budget = d.budget; renderBudget(); } })
      .catch(function () { });

    fetch('/api/snapshot').then(function (r) { return r.json(); })
      .then(function (s) { apply(s); })
      .catch(function () { setConn('down'); });

    var es = new EventSource('/api/stream');
    es.onopen = function () { setConn('live'); };
    es.onerror = function () { setConn('down'); };
    es.onmessage = function (ev) {
      setConn('live');
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === 'snapshot') apply(msg.data);
      else if (msg.type === 'delta') applyDelta(msg.data);
      else if (msg.type === 'heartbeat' && state.snap) {
        state.snap.server_time = msg.server_time;
        state.snap.summary = msg.summary || state.snap.summary;
        renderChrome();
      }
    };

    // 统一点击委托：MT 切换、新闻标签筛选、持仓/告警删除
    document.addEventListener('click', function (ev) {
      var target = ev.target;
      if (!target) return;

      // 1. News filter chip / ticker tag / event tag
      var nf = target.getAttribute && target.getAttribute('data-nf');
      if (nf) {
        state.newsFilter = (state.newsFilter === nf) ? '' : nf;
        if (state.page !== 'NEWS') setPage('NEWS');
        else renderGrid();
        return;
      }
      if (target.id === 'news-filter-clr') {
        state.newsFilter = '';
        renderGrid();
        return;
      }

      // 2. Delete portfolio position
      var dp = target.getAttribute && target.getAttribute('data-del-pos');
      if (dp) {
        fetch('/api/portfolio?id=' + encodeURIComponent(dp), { method: 'DELETE' })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d && d.portfolio && state.snap) { state.snap.portfolio = d.portfolio; renderGrid(); }
          }).catch(function () {});
        return;
      }

      // 3. Delete alert rule / clear triggered log
      var dr = target.getAttribute && target.getAttribute('data-del-rule');
      if (dr) {
        fetch('/api/alerts?id=' + encodeURIComponent(dr), { method: 'DELETE' })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d && d.alerts && state.snap) { state.snap.alerts = d.alerts; renderChrome(); renderGrid(); }
          }).catch(function () {});
        return;
      }
      if (target.id === 'btn-clear-alerts') {
        fetch('/api/alerts', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'clear' })
        }).then(function (r) { return r.json(); })
          .then(function (d) {
            if (d && d.alerts && state.snap) { state.snap.alerts = d.alerts; renderChrome(); renderGrid(); }
          }).catch(function () {});
        return;
      }

      // 4. MT 标记切换原文/译文（AC-D8.7）
      var node = target;
      while (node && node !== document.body) {
        if (node.className && String(node.className).indexOf('mt-badge') >= 0) break;
        node = node.parentNode;
      }
      if (!node || node === document.body) return;
      ev.preventDefault();
      var a = node.parentNode.querySelector('a[data-src]');
      if (!a) return;
      if (a.getAttribute('data-show') === 'orig') a.removeAttribute('data-show');
      else a.setAttribute('data-show', 'orig');
      applyTranslations();
    });

    // 新闻实时输入筛选
    document.addEventListener('input', function (ev) {
      if (ev.target && ev.target.id === 'news-filter') {
        state.newsFilter = ev.target.value || '';
        renderGrid();
        var inp = el('news-filter');
        if (inp) { inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
      }
    });

    // 表单提交委托：持仓 / 告警 / 自选
    document.addEventListener('submit', function (ev) {
      var f = ev.target;
      if (!f || !f.id) return;
      if (f.id === 'form-pos') {
        ev.preventDefault();
        var payload = {
          symbol: f.symbol.value, side: f.side.value,
          qty: parseFloat(f.qty.value), entry_price: parseFloat(f.entry_price.value),
          note: f.note.value
        };
        fetch('/api/portfolio', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }).then(function (r) { return r.json(); }).then(function (d) {
          state.formMsg = d.ok ? 'position saved' : (d.error || 'error');
          if (d.portfolio && state.snap) state.snap.portfolio = d.portfolio;
          renderGrid();
        }).catch(function () {});
      } else if (f.id === 'form-alert') {
        ev.preventDefault();
        var ap = {
          type: f.type.value, target: f.target.value,
          threshold: f.threshold.value === '' ? null : parseFloat(f.threshold.value),
          name: f.name.value
        };
        fetch('/api/alerts', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(ap)
        }).then(function (r) { return r.json(); }).then(function (d) {
          state.formMsg = d.ok ? 'alert rule saved' : (d.error || 'error');
          if (d.alerts && state.snap) state.snap.alerts = d.alerts;
          renderChrome();
          renderGrid();
        }).catch(function () {});
      } else if (f.id === 'form-watch') {
        ev.preventDefault();
        var wp = {
          us_equity: splitCsv(f.us_equity.value),
          cn_equity: splitCsv(f.cn_equity.value),
          crypto: splitCsv(f.crypto.value)
        };
        fetch('/api/watchlist', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(wp)
        }).then(function (r) { return r.json(); }).then(function (d) {
          state.watchlist = d;
          state.formMsg = d.ok ? 'watchlist saved' : (d.error || 'error');
          renderGrid();
        }).catch(function () {});
      }
    });

    window.setInterval(function () {
      el('m-clock').textContent = new Date().toTimeString().slice(0, 8);
      if (state.snap && state.snap.started_at) {
        var s = Math.floor((Date.now() - new Date(state.snap.started_at).getTime()) / 1000);
        el('m-uptime').textContent = s < 3600
          ? Math.floor(s / 60) + 'm' + (s % 60) + 's'
          : Math.floor(s / 3600) + 'h' + Math.floor((s % 3600) / 60) + 'm';
      }
    }, 1000);

    window.addEventListener('hashchange', function () {
      var raw2 = (window.location.hash || '').replace(/^#/, '');
      var ps = raw2.split('/').filter(Boolean);
      for (var j = 0; j < ps.length; j++) {
        var low2 = ps[j].toLowerCase();
        if (LANGS.indexOf(low2) >= 0 && low2 !== state.lang) { setLang(low2); return; }
        var up2 = ps[j].toUpperCase();
        if (PAGES.indexOf(up2) >= 0 && up2 !== state.page) { setPage(up2, true); return; }
      }
    });

    window.addEventListener('keydown', function (ev) {
      if (ev.target && /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) return;
      var n = -1;
      if (/^F[1-9]$/.test(ev.key)) n = parseInt(ev.key.slice(1), 10) - 1;
      if (n >= 0 && n < PAGES.length) {
        ev.preventDefault();
        setPage(PAGES[n]);
      } else if (ev.key === 'Escape') {
        ev.preventDefault();
        setPage('OVERVIEW');
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
