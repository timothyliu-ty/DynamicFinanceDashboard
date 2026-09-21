"""新闻适配器：15 个 RSS feed 并发抓取（AC-D3）。

要点：
- 单 feed 失败不影响其他 feed（各自独立 fetch，汇总 skipped）
- pubDate 解析失败 -> ts=None，UI 显示 "—"；绝不用当前时间冒充发布时间
- 按 link 去重；同一条被多 feed 报道时累计 feeds 列表
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from . import config
from . import net

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(text, limit=220):
    if not text:
        return ""
    s = _TAG_RE.sub(" ", text)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
          .replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">"))
    s = _WS_RE.sub(" ", s).strip()
    return s[:limit]


_NAIVE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S")


def _parse_date(raw):
    """RSS pubDate -> (ISO8601 本地时区, tz_assumed)。解析不出返回 (None, False)。

    实测三种格式并存（SPEC-DASH §2.2g）；只认 RFC822 会漏掉约 13% 的条目：
      RFC822        'Mon, 21 Sep 2026 10:00:00 GMT'   <- 多数 feed
      ISO8601       '2026-09-19T23:02:22Z'             <- Yahoo Finance（实测 49 条）
      无时区裸时间  '2026-09-21 02:13:49'               <- Investing.com（实测 19 条）
    裸时间不含时区信息，**不猜它是哪个时区**：按 UTC 解析并置 tz_assumed=True，
    UI 用 ~ 前缀标注，使「假定时间」与「端点明确给出的时间」可区分。
    """
    if not raw:
        return None, False
    s = raw.strip()

    try:
        dt = parsedate_to_datetime(s)
        if dt is not None:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc).astimezone().isoformat(timespec="seconds"), True
            return dt.astimezone().isoformat(timespec="seconds"), False
    except (TypeError, ValueError, IndexError):
        pass

    iso = (s[:-1] + "+00:00") if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc).astimezone().isoformat(timespec="seconds"), True
        return dt.astimezone().isoformat(timespec="seconds"), False
    except ValueError:
        pass

    for fmt in _NAIVE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return dt.astimezone().isoformat(timespec="seconds"), True
        except ValueError:
            continue
    return None, False


def _parse_feed(body, feed_name):
    root = ET.fromstring(body)
    items = root.findall(".//item")
    out = []
    for it in items:
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not title and not link:
            continue
        src = (it.findtext("source") or "").strip()
        ts, tz_assumed = _parse_date(it.findtext("pubDate"))
        out.append({
            "title": title,
            "link": link,
            "source": src or feed_name,
            "feed": feed_name,
            "summary": _clean(it.findtext("description")),
            "ts": ts,
            "ts_raw": (it.findtext("pubDate") or "").strip() or None,
            "tz_assumed": tz_assumed,
        })
    return out


def _one_feed(spec):
    name, url, category = spec
    res = net.fetch(url, timeout=config.HTTP_TIMEOUT)
    if not res["ok"]:
        return {"feed": name, "category": category, "url": url, "ok": False,
                "error": res.get("error"), "status": res.get("status"),
                "latency_ms": res.get("latency_ms"), "items": [],
                "fetched_at": res.get("fetched_at")}
    try:
        items = _parse_feed(res["body"], name)
    except ET.ParseError as e:
        return {"feed": name, "category": category, "url": url, "ok": False,
                "error": "XML 解析失败: %s" % e, "status": res.get("status"),
                "latency_ms": res.get("latency_ms"), "items": [],
                "fetched_at": res.get("fetched_at")}
    for it in items:
        it["category"] = category
    return {"feed": name, "category": category, "url": url, "ok": bool(items),
            "error": None if items else "无可解析条目", "status": res.get("status"),
            "latency_ms": res.get("latency_ms"), "items": items,
            "fetched_at": res.get("fetched_at")}


def news():
    """返回 {ok, items[], feeds[], skipped[], fetched_at, latency_ms}。"""
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(_one_feed, config.NEWS_FEEDS))

    merged, order = {}, []
    for r in results:
        for it in r["items"]:
            key = it["link"] or ("title:" + it["title"])
            if key in merged:
                if r["feed"] not in merged[key]["feeds"]:
                    merged[key]["feeds"].append(r["feed"])
            else:
                it["feeds"] = [r["feed"]]
                merged[key] = it
                order.append(key)

    items = [merged[k] for k in order]
    # 有时间的按时间倒序，无时间的排末尾（AC-D3.5）
    items.sort(key=lambda x: (x["ts"] is None, x["ts"] or ""), reverse=False)
    items.sort(key=lambda x: (x["ts"] or ""), reverse=True)

    feeds = [{"feed": r["feed"], "category": r["category"], "url": r["url"],
              "ok": r["ok"], "error": r["error"], "count": len(r["items"]),
              "latency_ms": r["latency_ms"]} for r in results]
    failed = [f for f in feeds if not f["ok"]]
    lats = [f["latency_ms"] for f in feeds if f["latency_ms"] is not None]
    return {
        "asset_class": "NEWS",
        "ok": any(f["ok"] for f in feeds),
        "items": items,
        "feeds": feeds,
        "skipped": [{"symbol": f["feed"], "reason": f["error"]} for f in failed],
        "error": ("%d/%d feed 失败" % (len(failed), len(feeds))) if failed else None,
        "source": "RSS",
        "endpoint": " | ".join(f["url"] for f in feeds),
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "latency_ms": max(lats) if lats else None,
        "as_of": None,
    }
