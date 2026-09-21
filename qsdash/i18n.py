"""国际化 / 新闻翻译（AC-D8）。

实测结论（SPEC-DASH §9，2026-09-21 本机）：
- Google 非官方 translate_a/single 本机 **HTTP 429**（10/10 全失败）→ 不可用
- LibreTranslate 公共镜像 400/502/307 → 不可用
- 唯一可用：**MyMemory**，12/12 成功，延迟 1.07-2.20s（均值 1.55s）
- 官方额度：匿名 **5000 字符/日**（带 de 邮箱 50000/日）

因此设计成「按需 + 双层缓存 + 额度护栏」：
  * 绝不批量预翻（517 条 ≈ 31,000 字符，超额度 6.2 倍，物理上不可能）
  * 只翻调用方点名的那几条；命中缓存不发网络请求
  * 当日额度将尽或 provider 报 quotaFinished 时**停止请求**并如实上报，绝不编造译文
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from . import config, net

PROVIDER = "MyMemory"
ENDPOINT = "https://api.mymemory.translated.net/get?q=%s&langpair=%s"

#: 官方文档：匿名 5000 字符/日。留出余量，避免刚好撞上 quotaFinished。
DAILY_CHAR_LIMIT = 5000
SAFETY_MARGIN = 250

#: 界面语言 -> MyMemory 目标语言代码
TARGETS = {"en": "en", "zh": "zh-CN"}

#: 实测 Autodetect / autodetect 均可用，省去调用方判断源语言
SOURCE = "Autodetect"

#: 单次请求最多处理多少条（护栏：防止前端一上来就点名上百条）
MAX_BATCH = 40

CACHE_PATH = os.path.join(config.DATA_DIR, "translation_cache.json")

_lock = threading.Lock()
_state = None  # {"entries": {...}, "usage": {"date": ..., "chars": N, "exhausted": bool}}


# --------------------------------------------------------------------- 状态
def _today():
    return datetime.date.today().isoformat()


def _blank_usage():
    return {"date": _today(), "chars": 0, "exhausted": False}


def _load():
    global _state
    if _state is not None:
        return _state
    data = {"entries": {}, "usage": _blank_usage()}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            disk = json.load(f)
        if isinstance(disk.get("entries"), dict):
            data["entries"] = disk["entries"]
        u = disk.get("usage") or {}
        data["usage"] = {
            "date": u.get("date") or _today(),
            "chars": int(u.get("chars") or 0),
            "exhausted": bool(u.get("exhausted")),
        }
    except (IOError, OSError, ValueError):
        pass
    _state = data
    _rollover(_state)
    return _state


def _rollover(st):
    """跨天则重置当日计数（但不丢弃译文缓存）。"""
    if st["usage"].get("date") != _today():
        st["usage"] = _blank_usage()
        return True
    return False


def _save(st):
    try:
        if not os.path.isdir(config.DATA_DIR):
            os.makedirs(config.DATA_DIR)
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, CACHE_PATH)
    except (IOError, OSError):
        pass


def _key(text, target):
    return hashlib.sha1((target + "\x00" + text).encode("utf-8")).hexdigest()[:20]


# --------------------------------------------------------------------- 额度
def budget():
    """当日额度快照，供 UI 展示。"""
    with _lock:
        st = _load()
        _rollover(st)
        u = st["usage"]
        remaining = max(0, DAILY_CHAR_LIMIT - SAFETY_MARGIN - u["chars"])
        return {
            "provider": PROVIDER,
            "date": u["date"],
            "limit": DAILY_CHAR_LIMIT,
            "used": u["chars"],
            "remaining": remaining,
            "exhausted": bool(u["exhausted"]) or remaining <= 0,
        }


# ----------------------------------------------------------------- 单条翻译
def translate(text, to):
    """翻译单条。返回 {ok, text, provider, cached, chars, error, langpair}。

    失败时 text 返回**原文**（绝不返回空串或编造内容），并带 error 说明。
    """
    text = (text or "").strip()
    target = TARGETS.get(to)
    if not target:
        return {"ok": False, "text": text, "cached": False, "chars": 0,
                "provider": None, "error": "不支持的目标语言: %s" % to, "langpair": None}
    if not text:
        return {"ok": False, "text": "", "cached": False, "chars": 0,
                "provider": None, "error": "空文本", "langpair": None}

    key = _key(text, target)
    with _lock:
        st = _load()
        _rollover(st)
        hit = st["entries"].get(key)
        if hit and hit.get("t"):
            return {"ok": True, "text": hit["t"], "cached": True, "chars": 0,
                    "provider": hit.get("p") or PROVIDER,
                    "error": None, "langpair": hit.get("lp"), "ts": hit.get("ts")}
        if st["usage"]["exhausted"]:
            return {"ok": False, "text": text, "cached": False, "chars": 0, "provider": None,
                    "error": "当日翻译额度已用尽（%d 字符/日）；不再发起请求" % DAILY_CHAR_LIMIT,
                    "langpair": None}
        cost = len(text)
        if st["usage"]["chars"] + cost > DAILY_CHAR_LIMIT - SAFETY_MARGIN:
            return {"ok": False, "text": text, "cached": False, "chars": 0, "provider": None,
                    "error": "本请求将超出当日额度（已用 %d / %d）；已停止翻译"
                             % (st["usage"]["chars"], DAILY_CHAR_LIMIT),
                    "langpair": None}
        # 预留额度，避免并发下超支
        st["usage"]["chars"] += cost

    langpair = "%s|%s" % (SOURCE, target)
    url = ENDPOINT % (urllib.parse.quote(text), urllib.parse.quote(langpair))
    r = net.fetch(url, timeout=20, retries=1)

    if not r.get("ok"):
        with _lock:
            st = _load()
            st["usage"]["chars"] = max(0, st["usage"]["chars"] - cost)  # 失败退还额度
            _save(st)
        return {"ok": False, "text": text, "cached": False, "chars": 0, "provider": None,
                "error": "网络失败: %s" % (r.get("error") or "未知"),
                "langpair": langpair}

    try:
        d = json.loads(r["body"])
    except ValueError:
        with _lock:
            st = _load()
            st["usage"]["chars"] = max(0, st["usage"]["chars"] - cost)
            _save(st)
        return {"ok": False, "text": text, "cached": False, "chars": 0, "provider": None,
                "error": "响应不是合法 JSON", "langpair": langpair}

    if d.get("quotaFinished"):
        with _lock:
            st = _load()
            st["usage"]["exhausted"] = True
            st["usage"]["chars"] = max(0, st["usage"]["chars"] - cost)
            _save(st)
        return {"ok": False, "text": text, "cached": False, "chars": 0, "provider": None,
                "error": "provider 报告当日额度已用尽（quotaFinished）", "langpair": langpair}

    status = d.get("responseStatus")
    out = ((d.get("responseData") or {}).get("translatedText") or "").strip()
    if status != 200 or not out:
        with _lock:
            st = _load()
            st["usage"]["chars"] = max(0, st["usage"]["chars"] - cost)
            _save(st)
        return {"ok": False, "text": text, "cached": False, "chars": 0, "provider": None,
                "error": "provider 返回 status=%s %s"
                         % (status, str(d.get("responseDetails") or "")[:80]),
                "langpair": langpair}

    entry = {"t": out, "p": PROVIDER, "lp": langpair, "ts": r.get("fetched_at"),
             "match": (d.get("responseData") or {}).get("match")}
    with _lock:
        st = _load()
        st["entries"][key] = entry
        # 缓存上限，避免无限增长（保留最近 4000 条）
        if len(st["entries"]) > 4000:
            for k in list(st["entries"])[:1000]:
                st["entries"].pop(k, None)
        _save(st)
    return {"ok": True, "text": out, "cached": False, "chars": cost, "provider": PROVIDER,
            "error": None, "langpair": langpair, "ts": entry["ts"], "match": entry["match"]}


# ----------------------------------------------------------------- 批量翻译
def translate_many(texts, to, workers=4):
    """并发翻译若干条（只翻未命中的）。返回 (results, budget)。"""
    texts = list(texts or [])[:MAX_BATCH]
    results = [None] * len(texts)
    if not texts:
        return results, budget()
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(texts)))) as ex:
        futs = {ex.submit(translate, t, to): i for i, t in enumerate(texts)}
        for fut, i in futs.items():
            try:
                results[i] = fut.result()
            except Exception as e:  # 适配器不得把异常抛给 HTTP 层
                results[i] = {"ok": False, "text": texts[i], "cached": False, "chars": 0,
                              "provider": None, "error": "内部错误: %s" % e, "langpair": None}
    return results, budget()


def stats():
    """缓存与额度统计（自测/CLI 用）。"""
    with _lock:
        st = _load()
        return {"cached_entries": len(st["entries"]), "budget": budget()}
