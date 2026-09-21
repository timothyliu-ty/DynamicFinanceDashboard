"""网络层契约（AC-D1）。不打外网。"""

from __future__ import annotations

from qsdash import net


def test_connection_failure_returns_ok_false_without_raising():
    """AC-D1.1：失败以 ok=False 表达，不向调用方抛异常。"""
    r = net.fetch("http://127.0.0.1:1/nope", timeout=2, retries=0)
    assert r["ok"] is False
    assert r["error"]
    assert r["endpoint"] == "http://127.0.0.1:1/nope"


def test_result_carries_provenance_fields():
    """AC-D1.4：每次抓取都带 fetched_at 与 latency_ms。"""
    r = net.fetch("http://127.0.0.1:1/nope", timeout=2, retries=0)
    for k in ["ok", "status", "body", "bytes", "latency_ms", "fetched_at", "endpoint", "error"]:
        assert k in r, k
    assert r["fetched_at"] and "T" in r["fetched_at"]


def test_no_retry_on_http_error(monkeypatch):
    """AC-D1.3：HTTP 4xx 不重试（端点否决不是抖动）。"""
    calls = {"n": 0}

    class FakeHTTPError(Exception):
        pass

    import urllib.error

    def fake_urlopen(req, timeout=None, context=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(net.urllib.request, "urlopen", fake_urlopen)
    r = net.fetch("http://example.invalid/x", retries=3)
    assert r["ok"] is False and r["status"] == 429
    assert calls["n"] == 1, "429 不应重试"
