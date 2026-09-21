"""翻译服务单元测试（AC-D8）。全部离线：net.fetch 被替换，不打网络。

重点验证的不是「能翻译」，而是失败路径**不撒谎**：
额度用尽 / provider 报错 / 网络失败时，必须返回原文 + 原因，
不得返回空串或看似合理的假译文（用户硬规则 4）。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from qsdash import i18n, net
from qsdash.server import make_server


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """每个用例独立缓存文件，且不污染真实 data/。"""
    monkeypatch.setattr(i18n, "CACHE_PATH", str(tmp_path / "translation_cache.json"))
    monkeypatch.setattr(i18n, "_state", None)
    yield


def _reply(text="随着通胀降温", status=200, quota=False, details=""):
    return json.dumps({"responseData": {"translatedText": text, "match": 0.85},
                       "quotaFinished": quota, "responseStatus": status,
                       "responseDetails": details, "matches": []})


def _net(monkeypatch, body=None, ok=True, error=None, counter=None):
    """把 net.fetch 换成假的；counter 记录调用次数与 URL。"""
    def fetch(url, headers=None, encoding="utf-8", timeout=None, retries=None):
        if counter is not None:
            counter["n"] += 1
            counter["urls"].append(url)
        return {"ok": ok, "status": 200 if ok else 503,
                "body": (body if ok else "") if body is not None else "",
                "bytes": len(body or ""), "latency_ms": 42, "attempt": 1,
                "fetched_at": "2026-09-21T10:00:00+08:00", "endpoint": url,
                "error": error, "encoding": encoding}
    monkeypatch.setattr(net, "fetch", fetch)


# --------------------------------------------------------------- 正常路径
def test_translate_returns_provider_text(monkeypatch):
    _net(monkeypatch, _reply())
    r = i18n.translate("Fed holds rates steady", "zh")
    assert r["ok"] is True
    assert r["text"] == "随着通胀降温"
    assert r["cached"] is False
    assert r["provider"] == i18n.PROVIDER
    assert r["chars"] == len("Fed holds rates steady")


def test_langpair_uses_autodetect_and_right_target(monkeypatch):
    """AC-D8.8：源语言交给 Autodetect，调用方不需要判断语种。"""
    c = {"n": 0, "urls": []}
    _net(monkeypatch, _reply(), counter=c)
    i18n.translate("Hello", "zh")
    assert "langpair=Autodetect%7Czh-CN" in c["urls"][0]
    i18n.translate("Hello two", "en")
    assert "langpair=Autodetect%7Cen" in c["urls"][1]


def test_second_call_is_served_from_cache(monkeypatch):
    """AC-D8.5：命中缓存不得再发网络请求。"""
    c = {"n": 0, "urls": []}
    _net(monkeypatch, _reply(), counter=c)
    i18n.translate("Same headline", "zh")
    r2 = i18n.translate("Same headline", "zh")
    assert c["n"] == 1, "第二次不应再打网络"
    assert r2["cached"] is True
    assert r2["chars"] == 0, "缓存命中不消耗额度"


def test_cache_persists_across_restart(monkeypatch):
    """AC-D8.5：重启后仍命中缓存，不重复消耗额度。"""
    c = {"n": 0, "urls": []}
    _net(monkeypatch, _reply(), counter=c)
    i18n.translate("Persisted headline", "zh")
    i18n._state = None            # 模拟进程重启
    r = i18n.translate("Persisted headline", "zh")
    assert r["cached"] is True and c["n"] == 1


def test_target_language_is_part_of_cache_key(monkeypatch):
    c = {"n": 0, "urls": []}
    _net(monkeypatch, _reply(), counter=c)
    i18n.translate("Headline", "zh")
    i18n.translate("Headline", "en")
    assert c["n"] == 2, "不同目标语言不能共用缓存"


# --------------------------------------------------------- 失败路径不撒谎
def test_network_failure_returns_original_text(monkeypatch):
    _net(monkeypatch, ok=False, error="HTTP 503 upstream down")
    src = "Nvidia shares jump after earnings beat"
    r = i18n.translate(src, "zh")
    assert r["ok"] is False
    assert r["text"] == src, "失败必须回原文，不能是空串或编造译文"
    assert "503" in r["error"]


def test_provider_error_status_is_not_ok(monkeypatch):
    _net(monkeypatch, _reply(text="", status=403, details="NO QUERY SPECIFIED"))
    r = i18n.translate("Something", "zh")
    assert r["ok"] is False and r["text"] == "Something"
    assert "403" in r["error"]


def test_broken_json_is_not_ok(monkeypatch):
    _net(monkeypatch, "{not json")
    r = i18n.translate("Something", "zh")
    assert r["ok"] is False and r["text"] == "Something"


def test_empty_translation_is_treated_as_failure(monkeypatch):
    """provider 返回 200 但译文为空 —— 不得当成成功。"""
    _net(monkeypatch, _reply(text="   "))
    r = i18n.translate("Something", "zh")
    assert r["ok"] is False and r["text"] == "Something"


def test_failed_request_refunds_budget(monkeypatch):
    """网络失败不能把额度算掉，否则重试会被自己的账本挡住。"""
    _net(monkeypatch, ok=False, error="boom")
    i18n.translate("x" * 100, "zh")
    assert i18n.budget()["used"] == 0


def test_unsupported_target_is_refused(monkeypatch):
    c = {"n": 0, "urls": []}
    _net(monkeypatch, _reply(), counter=c)
    r = i18n.translate("Hello", "fr")
    assert r["ok"] is False and c["n"] == 0


def test_empty_text_is_refused(monkeypatch):
    c = {"n": 0, "urls": []}
    _net(monkeypatch, _reply(), counter=c)
    r = i18n.translate("   ", "zh")
    assert r["ok"] is False and c["n"] == 0


# ------------------------------------------------------------------- 额度
def test_quota_finished_stops_further_requests(monkeypatch):
    """provider 报 quotaFinished 后必须停止请求，而不是继续打。"""
    c = {"n": 0, "urls": []}
    _net(monkeypatch, _reply(quota=True), counter=c)
    r1 = i18n.translate("First", "zh")
    assert r1["ok"] is False and "quotaFinished" in r1["error"]
    r2 = i18n.translate("Second", "zh")
    assert r2["ok"] is False
    assert c["n"] == 1, "额度用尽后不得再打网络"
    assert i18n.budget()["exhausted"] is True


def test_budget_refuses_before_exceeding_daily_limit(monkeypatch):
    c = {"n": 0, "urls": []}
    _net(monkeypatch, _reply(), counter=c)
    st = i18n._load()
    st["usage"]["chars"] = i18n.DAILY_CHAR_LIMIT - i18n.SAFETY_MARGIN - 5
    r = i18n.translate("a headline that is definitely longer than five chars", "zh")
    assert r["ok"] is False and c["n"] == 0
    assert "超" in r["error"] or "额度" in r["error"]


def test_budget_snapshot_shape(monkeypatch):
    _net(monkeypatch, _reply())
    i18n.translate("Hello", "zh")
    b = i18n.budget()
    assert b["limit"] == i18n.DAILY_CHAR_LIMIT
    assert b["used"] == 5
    assert b["remaining"] == i18n.DAILY_CHAR_LIMIT - i18n.SAFETY_MARGIN - 5
    assert b["provider"] == i18n.PROVIDER


# ------------------------------------------------------------------- 批量
def test_translate_many_preserves_order(monkeypatch):
    def fetch(url, headers=None, encoding="utf-8", timeout=None, retries=None):
        q = url.split("q=")[1].split("&")[0]
        return {"ok": True, "status": 200,
                "body": _reply(text="ZH:" + urllib.parse.unquote(q)), "bytes": 1,
                "latency_ms": 1, "attempt": 1, "fetched_at": "2026-09-21T10:00:00+08:00",
                "endpoint": url, "error": None, "encoding": encoding}
    monkeypatch.setattr(net, "fetch", fetch)
    texts = ["one", "two", "three", "four"]
    results, _ = i18n.translate_many(texts, "zh", workers=3)
    assert [r["text"] for r in results] == ["ZH:one", "ZH:two", "ZH:three", "ZH:four"]


def test_translate_many_caps_batch_size(monkeypatch):
    _net(monkeypatch, _reply())
    texts = ["t%d" % i for i in range(i18n.MAX_BATCH + 25)]
    results, _ = i18n.translate_many(texts, "zh")
    assert len(results) == i18n.MAX_BATCH


def test_translate_many_empty(monkeypatch):
    results, b = i18n.translate_many([], "zh")
    assert results == [] and b["limit"] == i18n.DAILY_CHAR_LIMIT


# ------------------------------------------------------------- HTTP 路由
class _Hub:
    def snapshot(self):
        return {"version": 1, "server_time": "2026-09-21T10:00:00+08:00",
                "summary": {}, "classes": {}}


@pytest.fixture
def live_server():
    srv = make_server(_Hub(), "127.0.0.1", 0)
    import threading
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def _post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def test_route_i18n_reports_locales_and_budget(live_server):
    st, d = _get(live_server + "/api/i18n")
    assert st == 200
    assert d["locales"] == ["en", "zh"]
    assert d["budget"]["limit"] == i18n.DAILY_CHAR_LIMIT
    assert d["source"] == "Autodetect"


def test_route_translate_roundtrip(monkeypatch, live_server):
    _net(monkeypatch, _reply())
    st, d = _post(live_server + "/api/translate", {"to": "zh", "texts": ["A", "B"]})
    assert st == 200 and d["ok"] is True
    assert [r["text"] for r in d["results"]] == ["随着通胀降温"] * 2
    assert d["budget"]["used"] == 2


def test_route_translate_rejects_bad_target(live_server):
    req = urllib.request.Request(live_server + "/api/translate",
                                data=json.dumps({"to": "fr", "texts": ["x"]}).encode(),
                                headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req, timeout=10)
    assert ei.value.code == 400


def test_route_translate_rejects_empty_texts(live_server):
    req = urllib.request.Request(live_server + "/api/translate",
                                data=json.dumps({"to": "zh", "texts": []}).encode(),
                                headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req, timeout=10)
    assert ei.value.code == 400


def test_route_unknown_post_is_404(live_server):
    req = urllib.request.Request(live_server + "/api/nope",
                                data=b"{}", headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req, timeout=10)
    assert ei.value.code == 404
