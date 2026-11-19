# -*- coding: utf-8 -*-
"""验链改造测试：pansou 批量验链优先、匿名直查兜底、全程不带 Cookie。

python3 tests/test_check_links.py 直接运行。
"""
import json
import os
import sys
from email.message import Message

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.pansou import PansouClient, PansouError  # noqa: E402
from app.quark import QuarkClient, QuarkError  # noqa: E402

CANDS = [
    {"url": "https://pan.quark.cn/s/aaa", "password": "1234"},
    {"url": "https://pan.quark.cn/s/bbb", "password": ""},
    {"url": "https://pan.quark.cn/s/ccc", "password": ""},
]


def make_pansou(fake_request):
    client = PansouClient("http://pansou:8888", "", "")
    client._request = fake_request
    return client


def test_check_links_ok():
    seen = {}

    def fake(method, path, body=None, auth=True, timeout=90):
        seen.update(method=method, path=path, body=body, timeout=timeout)
        return 200, {"results": [
            {"url": CANDS[0]["url"], "state": "ok"},
            {"url": CANDS[1]["url"], "state": "bad"},
            {"url": CANDS[2]["url"], "state": "uncertain"},
        ]}

    states = make_pansou(fake).check_links(CANDS)
    assert states == {CANDS[0]["url"]: "ok", CANDS[1]["url"]: "bad",
                      CANDS[2]["url"]: "uncertain"}, states
    # 请求形态：一次批量 POST，items 带 disk_type/url/password
    assert seen["method"] == "POST" and seen["path"] == "/api/check/links", seen
    assert seen["body"]["items"][0] == {"disk_type": "quark",
                                        "url": CANDS[0]["url"],
                                        "password": "1234"}, seen["body"]
    assert seen["timeout"] == PansouClient.CHECK_TIMEOUT, seen
    # data 包裹的返回也能识别
    def fake_wrapped(method, path, body=None, auth=True, timeout=90):
        return 200, {"data": {"results": [{"url": CANDS[0]["url"], "state": "ok"}]}}
    assert make_pansou(fake_wrapped).check_links(CANDS[:1]) == {CANDS[0]["url"]: "ok"}
    # 空候选不发请求
    assert make_pansou(None).check_links([]) == {}
    print("check_links ok")


def test_check_links_errors_raise():
    # 旧版 pansou 没有该接口（404）→ 必须抛错让上层兜底，不能静默
    def fake404(method, path, body=None, auth=True, timeout=90):
        return 404, {"error": "not found"}
    try:
        make_pansou(fake404).check_links(CANDS)
        raise AssertionError("404 应抛 PansouError")
    except PansouError:
        pass
    # 返回格式不识别 → 抛错
    def fake_bad_shape(method, path, body=None, auth=True, timeout=90):
        return 200, {"something": []}
    try:
        make_pansou(fake_bad_shape).check_links(CANDS)
        raise AssertionError("格式不识别应抛 PansouError")
    except PansouError:
        pass
    print("check_links errors ok")


def test_state_mapping():
    from app.main import Handler
    assert Handler._alive_from_state("ok") is True
    assert Handler._alive_from_state("bad") is False
    for s in ("locked", "uncertain", "unsupported", None, ""):
        assert Handler._alive_from_state(s) is None, s
    print("state mapping ok")


class FakeResp:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = 200
        self.headers = Message()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_anonymous_no_cookie_header():
    import app.quark as quark_mod
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["cookie"] = req.get_header("Cookie")
        return FakeResp({"code": 0, "data": {"list": [], "metadata": {"_total": 0}}})

    orig = quark_mod.urllib.request.urlopen
    quark_mod.urllib.request.urlopen = fake_urlopen
    try:
        anon = QuarkClient("", anonymous=True)  # 空 Cookie 不再报错
        anon.list_dir("0", size=1, max_pages=1)
        assert captured["cookie"] is None, captured
        # 普通模式带 Cookie 时仍发送
        normal = QuarkClient("a=1")
        normal.list_dir("0", size=1, max_pages=1)
        assert captured["cookie"] == "a=1", captured
    finally:
        quark_mod.urllib.request.urlopen = orig
    # 普通模式没 Cookie 仍报错
    try:
        QuarkClient("")
        raise AssertionError("普通模式空 Cookie 应报错")
    except QuarkError:
        pass
    print("anonymous header ok")


def _client_with_fake_share(token_exc=None, detail=None):
    client = QuarkClient("", anonymous=True)
    if token_exc is not None:
        client.share_token = lambda pwd_id, passcode="": (_ for _ in ()).throw(token_exc)
    else:
        client.share_token = lambda pwd_id, passcode="": "stoken-x"
    client.share_detail = lambda *a, **kw: (detail if detail is not None else [{"fid": "1"}])
    return client


def test_check_share_alive_tristate():
    url = "https://pan.quark.cn/s/abc123"
    # 活：token 换到且有顶层文件
    alive, top = _client_with_fake_share().check_share_alive(url)
    assert alive is True and len(top) == 1
    # 明确死链错误码 → False
    err = QuarkError("链接失效", payload={"code": 41004})
    alive, _ = _client_with_fake_share(token_exc=err).check_share_alive(url)
    assert alive is False
    # 失效类文案 → False
    err = QuarkError("分享不存在", payload={"code": 99999})
    alive, _ = _client_with_fake_share(token_exc=err).check_share_alive(url)
    assert alive is False
    # 需要提取码 → None（不算死）
    err = QuarkError("需要提取码", payload={"code": 41008})
    alive, _ = _client_with_fake_share(token_exc=err).check_share_alive(url)
    assert alive is None
    # 网络失败（无 payload）→ None，绝不判死
    err = QuarkError("网络请求失败: The read operation timed out")
    alive, _ = _client_with_fake_share(token_exc=err).check_share_alive(url)
    assert alive is None
    # token 换到但文件列表为空 → False
    alive, _ = _client_with_fake_share(detail=[]).check_share_alive(url)
    assert alive is False
    # 解析不出分享 ID → None
    alive, _ = _client_with_fake_share().check_share_alive("https://example.com/x")
    assert alive is None
    print("check_share_alive tristate ok")


def test_apply_alive_paths():
    from app.main import Handler
    handler = Handler.__new__(Handler)

    class FakePansou:
        def __init__(self, mode):
            self.mode = mode

        def check_links(self, head):
            if self.mode == "raise":
                raise PansouError("404")
            return {head[0]["url"]: "ok", head[1]["url"]: "bad",
                    head[2]["url"]: "locked"}

    # pansou 路径：五态映射，limit 外不动（保持 None）
    cands = [dict(c) for c in CANDS] + [{"url": "https://pan.quark.cn/s/ddd", "password": ""}]
    handler._apply_alive(FakePansou("ok"), cands, 3)
    assert [c["alive"] for c in cands] == [True, False, None, None], cands

    # 兜底路径：pansou 抛错 → 匿名直查（用假的匿名客户端替换）
    import app.main as main_mod
    orig = main_mod.QuarkClient

    class FakeAnon:
        def __init__(self, cookie, anonymous=False):
            assert anonymous is True and cookie == ""

        def check_share_alive(self, url, passcode=""):
            return (True, [{"fid": "1"}, {"fid": "2"}]) if url.endswith("aaa") else (None, [])

    main_mod.QuarkClient = FakeAnon
    try:
        cands = [dict(c) for c in CANDS]
        handler._apply_alive(FakePansou("raise"), cands, 3)
    finally:
        main_mod.QuarkClient = orig
    assert [c["alive"] for c in cands] == [True, None, None], cands
    assert cands[0]["top_count"] == 2, cands
    print("apply alive paths ok")


if __name__ == "__main__":
    test_check_links_ok()
    test_check_links_errors_raise()
    test_state_mapping()
    test_anonymous_no_cookie_header()
    test_check_share_alive_tristate()
    test_apply_alive_paths()
    print("ALL TESTS PASSED")
