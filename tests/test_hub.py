"""聚合新鲜度语义测试（AC-D4）。"""

from __future__ import annotations

import pytest

from qsdash import hub as hub_mod


def _good(cls="EQUITY"):
    return {"asset_class": cls, "ok": True, "quotes": [{"symbol": "X", "last": 1.0}],
            "items": [], "skipped": [], "error": None, "source": "s", "endpoint": "e",
            "fetched_at": "2026-09-21T10:00:00+08:00", "latency_ms": 5}


def _bad(cls="EQUITY"):
    return {"asset_class": cls, "ok": False, "quotes": [], "items": [], "skipped": [],
            "error": "HTTP 503 upstream down", "source": "s", "endpoint": "e",
            "fetched_at": "2026-09-21T10:01:00+08:00", "latency_ms": 5}


def test_successful_refresh_marks_live(monkeypatch):
    monkeypatch.setattr(hub_mod, "_fetch_class", lambda c: _good(c))
    h = hub_mod.Hub()
    r = h.refresh("EQUITY")
    assert r["ok"] is True and r["stale"] is False
    snap = h.snapshot()
    assert snap["classes"]["EQUITY"]["last_good_age_s"] == 0
    assert snap["summary"]["classes_ok"] == 1
    assert "FX" in snap["summary"]["degraded"]


def test_failure_keeps_last_good_but_marks_stale(monkeypatch):
    """AC-D4.2/D4.3：失败保留旧值，但必须 stale=True 且带年龄 —— 不能伪装成实时。"""
    state = {"ok": True}
    monkeypatch.setattr(hub_mod, "_fetch_class",
                        lambda c: _good(c) if state["ok"] else _bad(c))
    h = hub_mod.Hub()
    h.refresh("EQUITY")
    state["ok"] = False
    r = h.refresh("EQUITY")
    assert r["ok"] is False
    assert r["stale"] is True
    assert r["error"]
    assert r["quotes"] == [{"symbol": "X", "last": 1.0}], "应保留最后有效值"
    assert r["last_good_age_s"] is not None
    assert r["last_good_at"] == "2026-09-21T10:00:00+08:00"


def test_failure_without_history_has_no_fake_payload(monkeypatch):
    monkeypatch.setattr(hub_mod, "_fetch_class", lambda c: _bad(c))
    h = hub_mod.Hub()
    r = h.refresh("EQUITY")
    assert r["ok"] is False
    assert r["quotes"] == [] and r["items"] == []
    assert r["last_good_age_s"] is None


def test_adapter_exception_is_contained(monkeypatch):
    """AC-D4.4：适配器抛异常不得拖垮调度。"""
    def boom(cls):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(hub_mod, "_fetch_class", boom)
    h = hub_mod.Hub()
    h._safe_refresh("EQUITY")
    snap = h.snapshot()
    assert snap["classes"]["EQUITY"]["ok"] is False
    assert "kaboom" in snap["classes"]["EQUITY"]["error"]


def test_snapshot_shape_covers_all_classes(monkeypatch):
    monkeypatch.setattr(hub_mod, "_fetch_class", lambda c: _good(c))
    h = hub_mod.Hub()
    h.refresh_all()
    snap = h.snapshot()
    assert set(snap["classes"]) == set(hub_mod.CLASSES)
    assert snap["summary"]["classes_ok"] == len(hub_mod.CLASSES)
