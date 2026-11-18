# -*- coding: utf-8 -*-
"""目录浏览接口（含子文件夹）与 favicon 路由测试：python3 tests/test_folders_api.py。"""
import http.client
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["APP_PASSWORD"] = "testpw"

from app import main, store  # noqa: E402

TREE = {
    "0": [
        {"fid": "d-yingshi", "file_name": "影视", "dir": True},
        {"fid": "d-other", "file_name": "其他", "dir": True},
        {"fid": "f-root", "file_name": "根目录文件.mkv", "dir": False},
    ],
    "d-yingshi": [
        {"fid": "d-movie", "file_name": "电影", "dir": True},
        {"fid": "d-tv", "file_name": "电视剧", "dir": True},
    ],
    "d-movie": [],
    "d-tv": [],
    "d-other": [],
}


class FakeQuark:
    def list_dir(self, pdir_fid="0", size=100, max_pages=5):
        return list(TREE.get(pdir_fid, []))


def req(port, method, path, body=None, cookie=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    conn.request(method, path, json.dumps(body) if body is not None else None, headers)
    resp = conn.getresponse()
    data = resp.read()
    out = (resp.status, resp.headers, data)
    conn.close()
    return out


def main_test():
    with tempfile.TemporaryDirectory() as td:
        store.init(td)
        store.set_setting("quark_cookie", "dummy=1")
        orig_quark = main._quark
        main._quark = lambda: FakeQuark()
        server = ThreadingHTTPServer(("127.0.0.1", 0), main.Handler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            # 未登录访问目录接口应 401
            status, _, _ = req(port, "GET", "/api/quark/folders?fid=0")
            assert status == 401, status
            # 登录
            status, headers, _ = req(port, "POST", "/api/login", {"password": "testpw"})
            assert status == 200, status
            cookie = headers.get("Set-Cookie").split(";")[0]
            # 根目录：只返回文件夹，不含文件
            status, _, data = req(port, "GET", "/api/quark/folders?fid=0", cookie=cookie)
            folders = json.loads(data)["folders"]
            assert [f["name"] for f in folders] == ["影视", "其他"], folders
            # 子文件夹：影视 → 电影/电视剧（本次需求的核心）
            status, _, data = req(port, "GET", "/api/quark/folders?fid=d-yingshi", cookie=cookie)
            folders = json.loads(data)["folders"]
            assert [f["name"] for f in folders] == ["电影", "电视剧"], folders
            assert folders[0]["fid"] == "d-movie"
            # 叶子目录为空列表，前端据此提示可直接选此文件夹
            status, _, data = req(port, "GET", "/api/quark/folders?fid=d-movie", cookie=cookie)
            assert json.loads(data)["folders"] == []
            # favicon.ico：200 且是 ICO 魔数
            status, headers, data = req(port, "GET", "/favicon.ico")
            assert status == 200 and data[:4] == b"\x00\x00\x01\x00", (status, data[:8])
            # favicon.svg：200 且是 svg 文本
            status, _, data = req(port, "GET", "/favicon.svg")
            assert status == 200 and b"<svg" in data, status
            # 首页引用了图标与目录浏览器
            status, _, data = req(port, "GET", "/")
            html = data.decode("utf-8")
            assert "/favicon.svg" in html and "folderPicker" in html and "pickMovie" in html
            print("folders api + favicon ok")
        finally:
            main._quark = orig_quark
            server.shutdown()


if __name__ == "__main__":
    main_test()
    print("ALL TESTS PASSED")
