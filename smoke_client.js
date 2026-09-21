#!/usr/bin/env node
/* 客户端逻辑自测（AC-D8.1/D8.2/D8.6/D8.7/D8.9/D8.10）。
 *
 * 只做语法检查不等于页面能跑。这里用本机已有的 jsdom 真正执行 terminal.js：
 * 加载 index.html → 注入脚本 → 喂真实快照 fixture → 切中文 → 断言 DOM 行为。
 *
 * 场景一：翻译正常 —— 文案切换、译文贴上、MT 可切回原文、缓存不再请求。
 * 场景二：翻译额度用尽 —— **界面文案仍要能切**（AC-D8.10），标题必须保持原文，
 *         绝不出现空标题或编造译文（AC-D8.6/D8.9）。
 *
 * 全程离线：fetch 打桩（快照读 fixture，/api/translate 返回合成结果），不消耗额度。
 * jsdom 取自 DSH checkout，不作为本项目依赖。
 */
const path = require('path');
const fs = require('fs');

const HERE = __dirname;
const { JSDOM } = require('/Users/tianliu/tim_ai_tools/deepseek-harness/node_modules/jsdom');

const SNAP = JSON.parse(fs.readFileSync(path.join(HERE, 'tests/fixtures/snapshot_live.json'), 'utf8'));
const HTML = fs.readFileSync(path.join(HERE, 'qsdash/static/index.html'), 'utf8');
const JS = fs.readFileSync(path.join(HERE, 'qsdash/static/terminal.js'), 'utf8');

const results = [];
function check(name, cond, detail) {
  results.push([!!cond, name, detail || '']);
  console.log('  [' + (cond ? 'PASS' : 'FAIL') + '] ' + name.padEnd(54) + (detail || '').slice(0, 88));
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 5000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (fn()) return true; await sleep(50); }
  return false;
}

/* 建一个真跑起来的窗口；translateImpl 决定 /api/translate 的行为 */
function bootDom(translateImpl) {
  const errors = [];
  const dom = new JSDOM(HTML, { url: 'http://127.0.0.1:8848/', runScripts: 'outside-only', pretendToBeVisual: true });
  const win = dom.window;
  win.addEventListener('error', (e) => errors.push('error: ' + e.message));
  const stats = { calls: 0, lastBody: null };

  win.fetch = function (url, opts) {
    const u = String(url);
    if (u.indexOf('/api/snapshot') >= 0) return Promise.resolve({ json: () => Promise.resolve(SNAP) });
    if (u.indexOf('/api/i18n') >= 0) {
      return Promise.resolve({ json: () => Promise.resolve({
        locales: ['en', 'zh'], source: 'Autodetect', provider: 'MyMemory', max_batch: 40,
        budget: { provider: 'MyMemory', date: '2026-09-21', limit: 5000, used: 0,
                  remaining: 4750, exhausted: false } }) });
    }
    if (u.indexOf('/api/translate') >= 0) {
      stats.calls += 1;
      stats.lastBody = JSON.parse(opts.body);
      return Promise.resolve({ json: () => Promise.resolve(translateImpl(stats.lastBody)) });
    }
    return Promise.resolve({ json: () => Promise.resolve({}) });
  };
  win.EventSource = function () {
    const self = this;
    this.onopen = null; this.onerror = null; this.onmessage = null;
    setTimeout(() => { if (self.onopen) self.onopen(); }, 0);
    this.close = function () {};
  };
  Object.defineProperty(win.navigator, 'language', { value: 'en-US', configurable: true });
  win.eval(JS);
  return { win, errors, stats };
}

const zhButton = (win) => [...win.document.querySelectorAll('#lang-tog button')]
  .filter((b) => b.textContent === '\u4e2d\u6587')[0];
const fnBar = (win) => [...win.document.querySelectorAll('#fnbar .fn')];
const anchors = (win) => win.document.querySelectorAll('.news-title a[data-src]');
const visibleBadges = (win) => win.document.querySelectorAll('.mt-badge:not(.hidden)').length;

const okTranslate = (body) => ({
  ok: true, to: 'zh', provider: 'MyMemory', count: body.texts.length,
  results: body.texts.map((t) => ({ ok: true, text: '\u4e2d\u8bd1\uff1a' + t, cached: false,
                                    chars: t.length, provider: 'MyMemory', error: null })),
  budget: { provider: 'MyMemory', date: '2026-09-21', limit: 5000, used: 100,
            remaining: 4650, exhausted: false }
});

const exhaustedTranslate = (body) => ({
  ok: true, to: 'zh', provider: 'MyMemory', count: body.texts.length,
  results: body.texts.map((t) => ({ ok: false, text: t, cached: false, chars: 0,
                                    provider: null,
                                    error: '\u5f53\u65e5\u7ffb\u8bd1\u989d\u5ea6\u5df2\u7528\u5c3d\uff085000 \u5b57\u7b26/\u65e5\uff09\uff1b\u4e0d\u518d\u53d1\u8d77\u8bf7\u6c42' })),
  budget: { provider: 'MyMemory', date: '2026-09-21', limit: 5000, used: 5000,
            remaining: 0, exhausted: true }
});

(async () => {
  // ------------------------------------------------------------ 场景一
  console.log('\n=== 场景一：翻译正常 ===');
  const a = bootDom(okTranslate);
  const win = a.win;

  console.log('\n== 启动与英文默认界面 (AC-D8.2) ==');
  check('page booted without JS errors', a.errors.length === 0, a.errors.join(' | '));
  check('function bar rendered 7 pages', await until(() => fnBar(win).length === 7),
        'n=' + fnBar(win).length);
  check('F1 label is OVERVIEW in en', fnBar(win)[0].textContent.indexOf('OVERVIEW') >= 0,
        fnBar(win)[0].textContent);
  check('statusbar mode label en',
        win.document.getElementById('s-mode').textContent.indexOf('POLL') >= 0,
        win.document.getElementById('s-mode').textContent);
  check('clock label is CLOCK in en', win.document.getElementById('l-clock').textContent === 'CLOCK',
        win.document.getElementById('l-clock').textContent);
  check('grid rendered EQUITIES panel',
        win.document.getElementById('grid').textContent.indexOf('EQUITIES') >= 0);
  check('news rows rendered', anchors(win).length > 0, 'n=' + anchors(win).length);
  check('no translation requested while in en', a.stats.calls === 0, 'calls=' + a.stats.calls);
  check('titles show the source language in en', anchors(win)[0].textContent.length > 0,
        anchors(win)[0].textContent.slice(0, 48));

  console.log('\n== 切换到中文 (AC-D8.1/D8.2/D8.3) ==');
  check('language toggle has a 中文 button', !!zhButton(win));
  zhButton(win).click();
  await sleep(200);
  check('F1 label switched to 总览', fnBar(win)[0].textContent.indexOf('\u603b\u89c8') >= 0,
        fnBar(win)[0].textContent);
  check('static label 时钟 applied', win.document.getElementById('l-clock').textContent === '\u65f6\u949f');
  check('statusbar note switched',
        win.document.getElementById('s-note').textContent.indexOf('\u8f6e\u8be2') >= 0,
        win.document.getElementById('s-note').textContent);
  check('column header 最新 rendered',
        win.document.getElementById('grid').textContent.indexOf('\u6700\u65b0') >= 0);
  check('hash reflects language', win.location.hash.indexOf('#zh/') === 0, win.location.hash);
  check('lang persisted to localStorage', win.localStorage.getItem('qsdash.lang') === 'zh');
  check('documentElement lang set', win.document.documentElement.getAttribute('lang') === 'zh-CN');
  check('translation request made', await until(() => a.stats.calls > 0), 'calls=' + a.stats.calls);
  check('MT badges became visible', await until(() => visibleBadges(win) > 0),
        'badges=' + visibleBadges(win));
  check('lazy: batch bounded to <=30, not all 517',
        a.stats.lastBody && a.stats.lastBody.texts.length <= 30,
        'texts=' + (a.stats.lastBody ? a.stats.lastBody.texts.length : '?'));
  check('lazy: only displayed titles sent',
        a.stats.lastBody && a.stats.lastBody.texts.length <= anchors(win).length);
  const shown = win.document.querySelector('.news-title a[data-src][data-mt="1"]');
  check('translated anchor replaced', shown && shown.textContent.indexOf('\u4e2d\u8bd1\uff1a') === 0,
        shown ? shown.textContent.slice(0, 48) : '(none)');
  const badge = shown.parentNode.querySelector('.mt-badge');
  check('badge text is 机翻', badge.textContent === '\u673a\u7ffb', badge.textContent);
  check('budget line rendered',
        win.document.querySelector('[data-xl]').textContent.indexOf('\u673a\u7ffb\u989d\u5ea6') >= 0,
        win.document.querySelector('[data-xl]').textContent);

  console.log('\n== 切回原文 / 缓存幂等 (AC-D8.5/D8.7) ==');
  const origTitle = shown.getAttribute('data-src');
  badge.click();
  await sleep(120);
  check('clicking MT restores the original headline', shown.textContent === origTitle,
        shown.textContent.slice(0, 40));
  check('badge switched to 原文', badge.textContent === '\u539f\u6587', badge.textContent);
  badge.click();
  await sleep(120);
  check('clicking again returns to translation', shown.textContent.indexOf('\u4e2d\u8bd1\uff1a') === 0);

  const callsBefore = a.stats.calls;
  fnBar(win)[3].click();
  await sleep(300);
  fnBar(win)[0].click();
  await sleep(300);
  check('page switches reuse the cache, no new requests', a.stats.calls === callsBefore,
        'calls ' + callsBefore + ' -> ' + a.stats.calls);
  fnBar(win)[6].click();
  await sleep(250);
  check('F7 news page renders the feed-status panel',
        win.document.getElementById('grid').textContent.indexOf('\u6570\u636e\u6e90\u72b6\u6001') >= 0);
  check('no JS errors after all interactions', a.errors.length === 0, a.errors.join(' | '));

  // ------------------------------------------------------------ 场景二
  console.log('\n=== 场景二：翻译额度用尽 ===');
  const b = bootDom(exhaustedTranslate);
  const w2 = b.win;
  await until(() => fnBar(w2).length === 7);
  zhButton(w2).click();
  await sleep(250);
  await until(() => b.stats.calls > 0);

  console.log('\n== 界面仍可用，且不编造译文 (AC-D8.6/D8.9/D8.10) ==');
  check('UI labels still switch to 中文 when translation is dead',
        fnBar(w2)[0].textContent.indexOf('\u603b\u89c8') >= 0, fnBar(w2)[0].textContent);
  check('static labels still switch', w2.document.getElementById('l-clock').textContent === '\u65f6\u949f');
  check('translation was attempted', b.stats.calls > 0, 'calls=' + b.stats.calls);
  check('no MT badge shown on failure', visibleBadges(w2) === 0, 'badges=' + visibleBadges(w2));
  const allOrig = [...anchors(w2)].every((x) => x.textContent === x.getAttribute('data-src'));
  check('every headline still shows the original text (nothing fabricated)', allOrig,
        anchors(w2).length + ' anchors checked');
  check('no headline rendered empty',
        [...anchors(w2)].every((x) => x.textContent.trim().length > 0));
  check('headlines are still clickable links',
        [...anchors(w2)].every((x) => (x.getAttribute('href') || '').length > 0));
  check('quota state surfaced in the UI',
        w2.document.querySelector('[data-xl]').textContent.indexOf('\u5df2\u7528\u5c3d') >= 0,
        w2.document.querySelector('[data-xl]').textContent);
  check('market data unaffected by translation failure',
        w2.document.getElementById('grid').textContent.indexOf('\u6700\u65b0') >= 0);
  check('no JS errors in the failure path', b.errors.length === 0, b.errors.join(' | '));

  const passed = results.filter((r) => r[0]).length;
  console.log('\n' + '='.repeat(78));
  console.log('CLIENT: ' + passed + '/' + results.length + ' passed');
  results.filter((r) => !r[0]).forEach((r) => console.log('  FAILED: ' + r[1] + '  ' + r[2]));
  process.exit(passed === results.length ? 0 : 1);
})().catch((e) => { console.error('harness crashed:', e); process.exit(2); });
