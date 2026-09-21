/* QS-DASH 终端客户端。
   数据经 SSE /api/stream 推送；断线由 EventSource 自动重连。
   渲染铁律：ok=false 的面板置灰并显示错误原文，绝不把陈旧值当实时值展示。
   i18n（AC-D8）：界面文案 en/zh 切换；新闻翻译**按需**拉取 + 双层缓存 + 额度护栏，
   译文永远带 MT 标记，绝不把机翻当原文。 */
(function () {
  'use strict';

  var PAGES = ['OVERVIEW', 'EQUITY', 'FX', 'COMMODITIES', 'BONDS', 'CRYPTO', 'NEWS'];
  var CLASS_ORDER = ['EQUITY', 'FX', 'COMMODITIES', 'BONDS', 'CRYPTO'];
  var LANGS = ['en', 'zh'];

  /* 另一语言的类别名，在英文界面下作为暗色副标题出现 */
  var CLASS_ALT = {
    EQUITY: '股票', FX: '外汇', COMMODITIES: '大宗商品',
    BONDS: '债券', CRYPTO: '加密货币', NEWS: '市场情报'
  };

  var GROUP_ZH = {
    'US Equity': '美股', 'Global Index': '全球指数', 'China Index': 'A 股指数',
    'FX Spot': '即期', 'Futures (Global)': '国际期货',
    'US Treasury': '美国国债', 'TIPS': '通胀保值国债', 'Curve': '利差'
  };
  var CAT_ZH = { CRYPTO: '加密', MACRO: '宏观', GENERAL: '综合' };

  var I18N = {
    en: {
      OVERVIEW: 'OVERVIEW', EQUITY: 'EQUITIES', FX: 'FX', COMMODITIES: 'COMMODITIES',
      BONDS: 'BONDS', CRYPTO: 'CRYPTO', NEWS: 'NEWS', NEWS_PANEL: 'NEWS',
      FEED_STATUS: 'FEED STATUS',
      SUB: 'GLOBAL MULTI-ASSET TERMINAL',
      SYM: 'SYM', NAME: 'NAME', LAST: 'LAST', CHG: 'CHG', CHGP: 'CHG%', OPEN: 'OPEN',
      HIGH: 'HIGH', LOW: 'LOW', VOL: 'VOL', TIME: 'TIME',
      L_SESSION: 'SESSION', L_UPTIME: 'UPTIME', L_FEEDS: 'FEEDS', L_UPD: 'UPD', L_CLOCK: 'CLOCK',
      CONN_LIVE: 'LIVE', CONN_INIT: 'CONNECTING', CONN_DOWN: 'RECONNECTING',
      L_SRC: 'SRC', L_MODE: 'MODE', S_MODE: 'POLL / SSE \u00b7 STANDARD LIBRARY ONLY',
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
      TZ_TIP: 'feed supplied no timezone; parsed as UTC'
    },
    zh: {
      OVERVIEW: '总览', EQUITY: '股票', FX: '外汇', COMMODITIES: '大宗商品',
      BONDS: '债券', CRYPTO: '加密', NEWS: '新闻', NEWS_PANEL: '市场情报',
      FEED_STATUS: '数据源状态',
      SUB: '全球多资产实时终端',
      SYM: '代码', NAME: '名称', LAST: '最新', CHG: '涨跌', CHGP: '涨跌幅', OPEN: '开盘',
      HIGH: '最高', LOW: '最低', VOL: '成交量', TIME: '时间',
      L_SESSION: '会话', L_UPTIME: '运行', L_FEEDS: '数据源', L_UPD: '版本', L_CLOCK: '时钟',
      CONN_LIVE: '在线', CONN_INIT: '连接中', CONN_DOWN: '重连中',
      L_SRC: '来源', L_MODE: '模式', S_MODE: '轮询 / SSE \u00b7 仅标准库',
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
      TZ_TIP: '该源未提供时区，按 UTC 解析'
    }
  };

  var state = { snap: null, page: 'OVERVIEW', lang: 'en', prev: {} };

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

  /* 用 {0} {1} 占位，避免为语序差异写多份模板 */
  function sub(k, a, b, c, d2) {
    var s = t(k);
    s = s.replace('{0}', a === undefined ? '' : a).replace('{1}', b === undefined ? '' : b);
    s = s.replace('{2}', c === undefined ? '' : c).replace('{3}', d2 === undefined ? '' : d2);
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
        return ['LAST', 'CHG', 'CHGP', 'OPEN', 'HIGH', 'LOW', 'VOL', 'TIME'];
      }
      return ['LAST', 'CHG', 'CHGP', 'TIME'];
    }
    if (cls === 'FX') return ['LAST', 'CHG', 'CHGP', 'TIME'];
    if (cls === 'COMMODITIES') return ['LAST', 'CHG', 'CHGP', 'HIGH', 'LOW', 'TIME'];
    if (cls === 'BONDS') return ['LAST', 'CHG'];
    if (cls === 'CRYPTO') return ['LAST', 'CHG', 'CHGP', 'HIGH', 'LOW', 'VOL'];
    return ['LAST'];
  }

  function cellOf(q, cls, col) {
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
      default:     return { t: '\u2014', c: 'dim' };
    }
  }

  // ------------------------------------------------------------------ panels
  function panelShell(title, alt, metaHtml, footHtml, bodyHtml, dead) {
    return '<section class="panel' + (dead ? ' dead' : '') + '">' +
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
        if (cols[k] === 'LAST') {
          tb += '<td class="' + cell.c + '" data-flash="' + esc(cls + ':' + q.symbol) +
                '" data-val="' + esc(q.last) + '">' + cell.t + '</td>';
        } else {
          tb += '<td class="' + cell.c + '">' + cell.t + '</td>';
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

  function newsPanel(r, limit) {
    var items = (r.items || []).slice(0, limit || 60);
    var body;
    if (!items.length) {
      body = '<div style="padding:10px;color:#ff4d5e;font-size:11px;">' +
             esc(r.error || t('NO_NEWS')) + '</div>';
    } else {
      body = '<ul class="news-list">';
      for (var i = 0; i < items.length; i++) {
        var n = items[i];
        var tMark = n.tz_assumed ? '~' : '';
        var tTitle = n.tz_assumed ? ' title="' + esc(t('TZ_TIP')) + '"' : '';
        var title = n.title || '';
        body += '<li><div>' +
          '<span class="news-time"' + tTitle + '>' + tMark + clockOf(n.ts) + '</span>' +
          '<span class="news-src">' + esc(n.source || n.feed) + '</span>' +
          '<span class="news-title"><a href="' + esc(n.link) + '" target="_blank" rel="noopener"' +
          ' data-src="' + esc(title) + '">' + esc(title) + '</a>' +
          '<span class="mt-badge hidden" title="' + esc(t('MT_TIP')) + '">' +
          esc(t('MT')) + '</span></span>' +
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
    var meta = '<span>' + sub('N_ITEMS', (r.items || []).length,
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
                      meta, fh, body, !r.ok);
  }

  // ------------------------------------------------------- 翻译（AC-D8.3-D8.7）
  var xlate = { map: {}, budget: null, inflight: false };

  function visibleNewsAnchors() {
    return document.querySelectorAll('.news-title a[data-src]');
  }

  /* 只翻当前展示且尚未有结果的条目，最多 30 条（AC-D8.3） */
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

  /* 把已有结果贴回 DOM；失败的条目保持原文并标注（AC-D8.6/D8.9） */
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
  function renderGrid() {
    var snap = state.snap;
    var grid = el('grid');
    if (!snap || !snap.classes) { grid.innerHTML = ''; return; }
    var html = '';
    var page = state.page;
    var i;

    if (page === 'OVERVIEW') {
      for (i = 0; i < CLASS_ORDER.length; i++) {
        var r = snap.classes[CLASS_ORDER[i]];
        if (r) html += marketPanels(CLASS_ORDER[i], r);
      }
      if (snap.classes.NEWS) html += newsPanel(snap.classes.NEWS, 25);
    } else if (page === 'NEWS') {
      var nr = snap.classes.NEWS;
      if (nr) {
        var feeds = nr.feeds || [], parts = [];
        for (i = 0; i < feeds.length; i++) {
          parts.push('<span class="' + (feeds[i].ok ? '' : 'err') + '">' +
                     esc(feeds[i].feed) + ':' + (feeds[i].count || 0) + '</span>');
        }
        html += panelShell(t('FEED_STATUS'), '', '<span>' + sub('N_FEEDS', feeds.length) + '</span>',
                           parts.join(' &middot; '), '', false);
        html += newsPanel(nr, 400);
      }
    } else {
      var rr = snap.classes[page];
      if (rr) html += marketPanels(page, rr);
      if (snap.classes.NEWS) html += newsPanel(snap.classes.NEWS, 25);
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

  /* 静态文案的 id 映射，切换语言时整体刷新（AC-D8.2） */
  var STATIC_LABELS = [
    ['b-sub', 'SUB'], ['l-session', 'L_SESSION'], ['l-uptime', 'L_UPTIME'],
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
    renderGrid();
  }

  function boot() {
    /* 语言优先级：localStorage > URL hash > 浏览器语言 > en（AC-D8.1） */
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
      else if (msg.type === 'heartbeat' && state.snap) {
        state.snap.server_time = msg.server_time;
        state.snap.summary = msg.summary || state.snap.summary;
        renderChrome();
      }
    };

    /* 点 MT 标记 = 在原文 / 译文间切换（AC-D8.7） */
    document.addEventListener('click', function (ev) {
      var node = ev.target;
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
      if (/^F[1-7]$/.test(ev.key)) n = parseInt(ev.key.slice(1), 10) - 1;
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
