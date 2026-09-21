"""服务端安全与路由单元测试（AC-D5）。"""

from __future__ import annotations

import os

from qsdash import config
from qsdash.server import _safe_static_path


def test_static_path_allows_known_assets():
    for name in ["index.html", "terminal.css", "terminal.js"]:
        p = _safe_static_path(name)
        assert p and os.path.isfile(p), name


def test_static_path_blocks_traversal():
    """AC-D5.4：目录穿越必须被拒绝。"""
    for bad in ["../config.py", "../../etc/passwd", "..%2fconfig.py",
                "/../qsdash/config.py", "subdir/../../config.py"]:
        assert _safe_static_path(bad) is None, bad


def test_static_path_blocks_absolute_escape():
    assert _safe_static_path("/etc/passwd") is None


def test_missing_file_returns_none():
    assert _safe_static_path("nope.js") is None


def test_static_dir_exists_and_is_self_contained():
    """AC-D6.6：不得引用任何外部 CDN / 字体（离线可渲染）。"""
    for name in ["index.html", "terminal.css", "terminal.js"]:
        with open(os.path.join(config.STATIC_DIR, name), encoding="utf-8") as f:
            text = f.read()
        for bad in ["http://", "https://", "//cdn", "fonts.googleapis", "unpkg.com", "jsdelivr"]:
            assert bad not in text, "%s 引用了外部资源: %s" % (name, bad)
