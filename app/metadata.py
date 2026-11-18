# -*- coding: utf-8 -*-
"""
影视元数据检索（找资源之前先定位条目：海报、规范片名、年份、类型、评分）。

两个来源，统一成同一种条目结构：
  - TMDB（主源）：官方 API，需在设置里填 API key；字段全（海报/评分/简介）。
  - 豆瓣 suggest（补充源）：网页联想接口，免 key；国产片名校准好，
    但无评分字段、非官方接口，且对服务端请求指纹敏感（实测机房环境
    多为 403/超时，属正常现象）——失败静默跳过，绝不挡主流程。

条目结构：
  {source, source_id, kind: "movie"|"tv", title, original_title,
   year, poster, rating (float|None), overview, url}
"""

import json
import urllib.parse
import urllib.request

TIMEOUT = 8
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w342"
DOUBAN_SUGGEST = "https://movie.douban.com/j/subject_suggest"


def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def search_tmdb(query, api_key, limit=12):
    """TMDB /search/multi：电影与剧集一起搜，只保留 movie/tv。"""
    if not api_key:
        return []
    qs = urllib.parse.urlencode({
        "api_key": api_key, "query": query,
        "language": "zh-CN", "include_adult": "false", "page": 1,
    })
    data = _get_json(f"{TMDB_API}/search/multi?{qs}")
    items = []
    for r in data.get("results", []):
        media = r.get("media_type")
        if media not in ("movie", "tv"):
            continue
        date = r.get("release_date") or r.get("first_air_date") or ""
        poster = r.get("poster_path")
        items.append({
            "source": "tmdb",
            "source_id": str(r.get("id", "")),
            "kind": media,
            "title": r.get("title") or r.get("name") or "",
            "original_title": r.get("original_title") or r.get("original_name") or "",
            "year": date[:4],
            "poster": (TMDB_IMG + poster) if poster else "",
            "rating": round(float(r["vote_average"]), 1) if r.get("vote_average") else None,
            "overview": (r.get("overview") or "")[:200],
            "url": f"https://www.themoviedb.org/{media}/{r.get('id', '')}",
        })
        if len(items) >= limit:
            break
    return items


def search_douban(query, limit=10):
    """豆瓣 subject_suggest：返回片名/年份/类型/海报，无评分。失败抛异常由上层吞掉。"""
    qs = urllib.parse.urlencode({"q": query})
    data = _get_json(f"{DOUBAN_SUGGEST}?{qs}", headers={
        "User-Agent": _UA,
        "Referer": "https://movie.douban.com/",
        "Accept": "application/json, text/plain, */*",
    })
    items = []
    for r in data if isinstance(data, list) else []:
        kind = {"movie": "movie", "tv": "tv"}.get(r.get("type"))
        if not kind:
            continue
        items.append({
            "source": "douban",
            "source_id": str(r.get("id", "")),
            "kind": kind,
            "title": r.get("title") or "",
            "original_title": r.get("sub_title") or "",
            "year": str(r.get("year") or ""),
            "poster": r.get("img") or "",
            "rating": None,
            "overview": "",
            "url": f"https://movie.douban.com/subject/{r.get('id', '')}/",
        })
        if len(items) >= limit:
            break
    return items


def search_all(query, tmdb_api_key=""):
    """并发查两个源；任一源失败不影响另一个。返回 (items, notes)。

    TMDB 在前（字段全），豆瓣在后（国产补充）；不做跨源去重——
    同一部片两个源各出一张卡，用户自己认，反而能对着豆瓣条目校准。
    """
    import threading
    out = {"tmdb": [], "douban": []}
    notes = []

    def run(name, fn):
        try:
            out[name] = fn()
        except Exception as e:
            notes.append(f"{name} 检索失败（已跳过）：{e}")

    threads = []
    if tmdb_api_key:
        threads.append(threading.Thread(
            target=run, args=("tmdb", lambda: search_tmdb(query, tmdb_api_key))))
    else:
        notes.append("未配置 TMDB API key，仅查豆瓣（可在设置页填入）")
    threads.append(threading.Thread(
        target=run, args=("douban", lambda: search_douban(query))))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=TIMEOUT + 2)
    return out["tmdb"] + out["douban"], notes
