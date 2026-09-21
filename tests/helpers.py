"""测试工具：离线 fixture 与假 fetch。

测试不打网络：所有适配器测试都把 qsdash.markets.net.fetch 换成假实现，
返回 tests/fixtures 下真实抓取的样本。样本结构稳定，数值会随行情变化，
因此断言锁定的是**字段索引**（回归护栏）与**内部一致性**，而不是具体价格。
"""

from __future__ import annotations

import json
import os

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return f.read()


def fake_fetch(mapping, fail_error="HTTP 503 upstream down"):
    """mapping: [(url_substring, fixture_filename), ...]；未命中的 URL 一律失败。"""
    def _fetch(url, headers=None, encoding="utf-8", timeout=None, retries=None):
        for sub, name in mapping:
            if sub in url:
                body = fixture(name)
                return {"ok": True, "status": 200, "body": body, "bytes": len(body),
                        "latency_ms": 42, "attempt": 1,
                        "fetched_at": "2026-09-21T10:00:00+08:00", "endpoint": url,
                        "error": None, "encoding": encoding}
        return {"ok": False, "status": 503, "body": "", "bytes": 0, "latency_ms": 7,
                "attempt": 1, "fetched_at": "2026-09-21T10:00:00+08:00",
                "endpoint": url, "error": fail_error, "encoding": encoding}
    return _fetch


def sina_fields(text):
    """把 fixture 还原为 {key: [fields]}。"""
    out = {}
    for line in text.strip().split("\n"):
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip().replace("var hq_str_", "").strip()] = v.strip().rstrip(";").strip('"').split(",")
    return out
