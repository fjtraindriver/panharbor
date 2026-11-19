# -*- coding: utf-8 -*-
"""元数据检索测试（TMDB/豆瓣解析、失败静默、接口）：python3 tests/test_metadata.py。"""
import http.client
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["APP_PASSWORD"] = "testpw"

from app import main, metadata, store  # noqa: E402

TMDB_SAMPLE = {"results": [
    {"id": 693134, "media_type": "movie", "title": "沙丘2",
     "original_title": "Dune: Part Two", "release_date": "2024-02-27",
     "poster_path": "/x.jpg", "vote_average": 8.16, "overview": "保罗踏上复仇之路。"},
    {"id": 693135, "media_type": "tv", "name": "沙丘：预言",
     "original_name": "Dune: Prophecy", "first_air_date": "2024-11-17",
     "poster_path": None, "vote_average": 0, "overview": ""},
    {"id": 42, "media_type": "person", "name": "某演员"},
]}
DOUBAN_SAMPLE = [
    {"id": "34780991", "type": "movie", "title": "沙丘2", "sub_title": "Dune: Part Two",
     "year": "2024", "img": "https://img.example/p.jpg"},
    {"id": "999", "type": "book", "title": "沙丘（书）", "sub_title": "", "year": "2020", "img": ""},
]


def test_parse():
    orig = metadata._get_json
    try:
        metadata._get_json = lambda url, headers=None: TMDB_SAMPLE
        items = metadata.search_tmdb("沙丘", "key")
        assert len(items) == 2, items  # person 被过滤
        m = items[0]
        assert m["kind"] == "movie" and m["title"] == "沙丘2" and m["year"] == "2024"
        assert m["rating"] == 8.2 and m["poster"].endswith("/x.jpg")
        assert items[1]["kind"] == "tv" and items[1]["rating"] is None  # 0 分视为无评分
        metadata._get_json = lambda url, headers=None: DOUBAN_SAMPLE
        items = metadata.search_douban("沙丘")
        assert len(items) == 1 and items[0]["source"] == "douban"
        assert items[0]["rating"] is None and items[0]["year"] == "2024"
        print("parse ok")
    finally:
        metadata._get_json = orig


def test_search_all_tolerance():
    orig_t, orig_d = metadata.search_tmdb, metadata.search_douban
    try:
        metadata.search_tmdb = lambda q, k: [{"source": "tmdb", "title": "A"}]

        def boom(q):
            raise RuntimeError("403")
        metadata.search_douban = boom
        items, notes = metadata.search_all("x", "key")
        assert [i["title"] for i in items] == ["A"], items
        assert any("douban" in n for n in notes), notes
        # 无 key 时不查 TMDB、给出提示，豆瓣仍查
        metadata.search_tmdb = lambda q, k: (_ for _ in ()).throw(AssertionError("不应调用"))
        metadata.search_douban = lambda q: [{"source": "douban", "title": "B"}]
        items, notes = metadata.search_all("x", "")
        assert [i["title"] for i in items] == ["B"] and any("TMDB" in n for n in notes)
        print("tolerance ok")
    finally:
        metadata.search_tmdb, metadata.search_douban = orig_t, orig_d


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


def test_api():
    with tempfile.TemporaryDirectory() as td:
        store.init(td)
        orig = metadata.search_all
        metadata.search_all = lambda q, k: ([{"source": "tmdb", "title": "沙丘2", "kind": "movie"}], [])
        server = ThreadingHTTPServer(("127.0.0.1", 0), main.Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            status, _, _ = req(port, "GET", "/api/meta/search?q=x")
            assert status == 401, status
            status, headers, _ = req(port, "POST", "/api/login", {"password": "testpw"})
            cookie = headers.get("Set-Cookie").split(";")[0]
            status, _, data = req(port, "GET", "/api/meta/search?q=%E6%B2%99%E4%B8%98", cookie=cookie)
            payload = json.loads(data)
            assert status == 200 and payload["items"][0]["title"] == "沙丘2", payload
            status, _, _ = req(port, "GET", "/api/meta/search?q=", cookie=cookie)
            assert status == 400, status
            # 首页含两段式元素与版本号资源
            status, _, data = req(port, "GET", "/")
            html = data.decode("utf-8")
            assert "metaResults" in html and "directSearchBtn" in html and "setTmdbKey" in html
            assert "/app.js?v=0.4.1" in html
            print("api ok")
        finally:
            metadata.search_all = orig
            server.shutdown()


if __name__ == "__main__":
    test_parse()
    test_search_all_tolerance()
    test_api()
    print("ALL TESTS PASSED")
