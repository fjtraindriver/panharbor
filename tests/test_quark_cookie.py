# -*- coding: utf-8 -*-
"""夸克 Cookie 轮换回写 + 保活单元测试：python3 tests/test_quark_cookie.py 直接运行。"""
import io
import json
import os
import sys
import tempfile
from email.message import Message

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.quark import QuarkClient, REQUEST_TIMEOUT, merge_set_cookies  # noqa: E402


def test_merge():
    base = "__pus=aaa; __puus=old; b-user-id=42"
    # 轮换已有字段：只换 __puus，其余不动、顺序不变
    out = merge_set_cookies(base, ["__puus=new; expires=Wed, 01 Jan 2030 00:00:00 GMT; path=/"])
    assert out == "__pus=aaa; __puus=new; b-user-id=42", out
    # 新增字段追加到末尾
    out = merge_set_cookies(base, ["__kp=xyz; path=/"])
    assert out == base + "; __kp=xyz", out
    # 值里带 = 不能被截断
    out = merge_set_cookies(base, ["__pus=ab==; path=/"])
    assert "__pus=ab==" in out, out
    # 多个 Set-Cookie 一次合并
    out = merge_set_cookies(base, ["__puus=n2; path=/", "__kp=k2; path=/"])
    assert "__puus=n2" in out and "__kp=k2" in out, out
    # 空值 = 删除该字段
    out = merge_set_cookies(base, ["__puus=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/"])
    assert "__puus" not in out and "__pus=aaa" in out, out
    # 没变化时原样返回（不触发写库）
    assert merge_set_cookies(base, []) == base
    assert merge_set_cookies(base, ["__puus=old; path=/"]) == base
    # 坏 header 跳过
    assert merge_set_cookies(base, ["", "no-equals", "=v; path=/"]) == base
    print("merge ok")


class FakeResp:
    def __init__(self, payload, set_cookies):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = 200
        self.headers = Message()
        for sc in set_cookies:
            self.headers.add_header("Set-Cookie", sc)

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_call_absorbs():
    import app.quark as quark_mod
    saved = {}
    seen = {}
    client = QuarkClient("__pus=aaa; __puus=old",
                         on_cookie_update=lambda c: saved.update(cookie=c))
    orig = quark_mod.urllib.request.urlopen

    def fake_urlopen(req, timeout=None):
        seen["timeout"] = timeout
        return FakeResp(
            {"code": 0, "data": {"list": [], "metadata": {"_total": 0}}},
            ["__puus=rotated; expires=Wed, 01 Jan 2030 00:00:00 GMT; path=/"])

    quark_mod.urllib.request.urlopen = fake_urlopen
    try:
        client.list_dir("0", size=1, max_pages=1)
    finally:
        quark_mod.urllib.request.urlopen = orig
    assert client.cookie == "__pus=aaa; __puus=rotated", client.cookie
    assert saved.get("cookie") == client.cookie, saved
    # 跨地域访问放宽后的超时：常量与实际传给 urlopen 的值都必须是 120
    assert REQUEST_TIMEOUT == 120, REQUEST_TIMEOUT
    assert seen.get("timeout") == 120, seen
    print("call absorb ok")


def test_keepalive_records():
    from app import main, store
    with tempfile.TemporaryDirectory() as td:
        store.init(td)
        # 未配置 Cookie：直接跳过，不写记录
        assert main._keepalive_once() is False
        assert store.get_setting("quark_keepalive_at") == ""
        # 配置后成功：记录 ok=1
        store.set_setting("quark_cookie", "dummy=1")

        class OkClient:
            def list_dir(self, *a, **kw):
                return []

        orig = main._quark
        main._quark = lambda: OkClient()
        try:
            assert main._keepalive_once() is True
        finally:
            main._quark = orig
        assert store.get_setting("quark_keepalive_ok") == "1"
        assert store.get_setting("quark_keepalive_at").isdigit()

        # 失败：记录 ok=0 和错误信息，不抛
        class BadClient:
            def list_dir(self, *a, **kw):
                raise RuntimeError("cookie expired")

        main._quark = lambda: BadClient()
        try:
            assert main._keepalive_once() is False
        finally:
            main._quark = orig
        assert store.get_setting("quark_keepalive_ok") == "0"
        assert "cookie expired" in store.get_setting("quark_keepalive_msg")
        # 保活间隔：24h ~ 27h 之间
        for _ in range(20):
            d = main._keepalive_delay()
            assert 24 * 3600 <= d <= 27 * 3600, d
    print("keepalive ok")


def test_store_updater():
    from app import store
    with tempfile.TemporaryDirectory() as td:
        store.init(td)
        up = store.setting_updater("quark_cookie")
        up("a=1")
        assert store.get_setting("quark_cookie") == "a=1"
        up("a=1")  # 同值不重复写（行为等价，至少不报错）
        up("")     # 空值忽略，不能把已存 Cookie 清掉
        assert store.get_setting("quark_cookie") == "a=1"
        up("a=2")
        assert store.get_setting("quark_cookie") == "a=2"
    print("store updater ok")


if __name__ == "__main__":
    test_merge()
    test_call_absorbs()
    test_keepalive_records()
    test_store_updater()
    print("ALL TESTS PASSED")
