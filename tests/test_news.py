"""新闻解析测试（AC-D3）。"""

from __future__ import annotations

from qsdash import net, news
from tests.helpers import fake_fetch


def _patch(monkeypatch, mapping):
    monkeypatch.setattr(net, "fetch", fake_fetch(mapping))


def test_rss_parses_title_link_date(monkeypatch):
    _patch(monkeypatch, [("cnbc.com", "rss_cnbc.xml")])
    r = news.news()
    assert r["ok"] is True
    assert len(r["items"]) > 0
    it = r["items"][0]
    assert it["title"] and it["link"]
    assert it["ts"], "pubDate 应能解析为 ISO"
    assert it["source"], "source 缺失时应回填 feed 名"
    assert r["feeds"][0]["count"] > 0


def test_google_news_has_source_field(monkeypatch):
    _patch(monkeypatch, [("news.google.com", "rss_google.xml")])
    r = news.news()
    assert r["ok"] is True
    assert all(i["ts"] for i in r["items"])


def test_dedupe_by_link_accumulates_feeds(monkeypatch):
    """AC-D3.3：同一条新闻被两个 feed 收录时只保留一条，并记录 feeds 列表。"""
    xml = ('<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
           '<item><title>Same Story</title><link>https://x.example/a</link>'
           '<pubDate>Mon, 21 Sep 2026 10:00:00 GMT</pubDate></item>'
           '</channel></rss>')
    calls = {"n": 0}

    def fetch(url, **kw):
        calls["n"] += 1
        return {"ok": True, "status": 200, "body": xml, "bytes": len(xml),
                "latency_ms": 1, "attempt": 1,
                "fetched_at": "2026-09-21T10:00:00+08:00", "endpoint": url, "error": None}

    monkeypatch.setattr(net, "fetch", fetch)
    r = news.news()
    assert calls["n"] == len(news.config.NEWS_FEEDS)
    same = [i for i in r["items"] if i["link"] == "https://x.example/a"]
    assert len(same) == 1
    assert len(same[0]["feeds"]) == len(news.config.NEWS_FEEDS)


def test_unparseable_date_is_none_not_now(monkeypatch):
    """AC-D3.4：时间解析失败必须是 None，不得用当前时间冒充。"""
    xml = ('<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
           '<item><title>No Date</title><link>https://x.example/b</link></item>'
           '</channel></rss>')

    def fetch(url, **kw):
        return {"ok": True, "status": 200, "body": xml, "bytes": len(xml),
                "latency_ms": 1, "attempt": 1, "fetched_at": "2026-09-21T10:00:00+08:00",
                "endpoint": url, "error": None}

    monkeypatch.setattr(net, "fetch", fetch)
    r = news.news()
    it = [i for i in r["items"] if i["title"] == "No Date"][0]
    assert it["ts"] is None


def test_failed_feed_does_not_kill_others(monkeypatch):
    """AC-D3.1：单个 feed 失败不影响其他 feed。"""
    _patch(monkeypatch, [("cnbc.com/id/100003114", "rss_cnbc.xml")])
    r = news.news()
    assert r["ok"] is True
    assert len(r["items"]) > 0
    bad = [f for f in r["feeds"] if not f["ok"]]
    assert len(bad) == len(news.config.NEWS_FEEDS) - 1
