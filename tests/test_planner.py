# -*- coding: utf-8 -*-
"""计划生成器单元测试：python3 tests/test_planner.py 直接运行。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.planner import build_plan, parse_season_episode  # noqa: E402

GB = 1024 ** 3
MB = 1024 ** 2


def f(name, size, parent="0", is_dir=False):
    return {"fid": "fid-" + name, "token": "tok-" + name, "name": name,
            "size": size, "dir": is_dir, "parent_fid": parent,
            "path": name}


def test_parse():
    assert parse_season_episode("某剧.S01E05.1080p.mkv") == (1, 5)
    assert parse_season_episode("某剧 第12集.mp4") == (1, 12)
    assert parse_season_episode("EP03.mkv") == (1, 3)
    assert parse_season_episode("03.某剧.mkv") == (1, 3)
    assert parse_season_episode("某电影.2024.2160p.mkv") is None
    print("parse ok")


def test_tv_plan():
    files = [
        f("某剧", 0, is_dir=True),
        f("某剧.S01E01.1080p.mkv", 2 * GB, parent="fid-某剧"),
        f("某剧.S01E01.720p.mkv", 800 * MB, parent="fid-某剧"),   # 重复版本，应跳过
        f("某剧.S01E02.1080p.mkv", 2 * GB, parent="fid-某剧"),
        f("某剧.S01E04.1080p.mkv", 2 * GB, parent="fid-某剧"),    # 缺 E03
        f("某剧.S01E02.1080p.srt", 100 * 1024, parent="fid-某剧"),  # 字幕保留
        f("关注公众号.txt", 2048, parent="fid-某剧"),              # 杂文件跳过
        f("预告片.mp4", 5 * MB, parent="fid-某剧"),                # 预告跳过
        f("某剧.S01E03.样片.mp4", 10 * MB, parent="fid-某剧"),    # 小文件跳过
    ]
    plan = build_plan(files, "某剧", "tv", candidate_title="某剧 2026")
    names = {i["new_name"] for i in plan["keep"]}
    assert "某剧.S01E01.mkv" in names
    assert "某剧.S01E02.mkv" in names
    assert "某剧.S01E02.srt" in names
    assert "某剧.S01E04.mkv" in names
    reasons = " ".join(s["reason"] for s in plan["skip"])
    assert "重复版本" in reasons and "杂文件" in reasons
    assert any("缺集" in w and "E03" in w for w in plan["warnings"]), plan["warnings"]
    print("tv plan ok")


def test_movie_plan():
    files = [
        f("新建文件夹-260831", 0, is_dir=True),
        f("唐人街探案3.2021.1080p.mkv", 3 * GB, parent="d"),
        f("唐人街探案3.2021.720p.mp4", 1 * GB, parent="d"),
        f("海报.jpg", 300 * 1024, parent="d"),
    ]
    plan = build_plan(files, "唐人街探案3", "movie", candidate_title="唐人街探案3 2021")
    names = {i["new_name"] for i in plan["keep"]}
    assert names == {"唐人街探案3 (2021).mkv"}, names
    print("movie plan ok")


if __name__ == "__main__":
    test_parse()
    test_tv_plan()
    test_movie_plan()
    print("ALL TESTS PASSED")
