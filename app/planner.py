# -*- coding: utf-8 -*-
"""
转存计划生成器：把分享的完整文件清单按规则清洗成「将存 / 将跳过」计划。

规则口径见蓝图第 5 节：高置信才跳过，不确定一律保留并标黄；
同一集多版本按质量偏好留最佳一份；改名在转存后由执行器用网盘改名接口完成，
这里只负责算出每个保留文件的新名字。
"""

import re

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".mov", ".rmvb", ".rm",
              ".webm", ".flv", ".wmv", ".mpg", ".mpeg", ".iso"}
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz"}
JUNK_EXTS = {".txt", ".html", ".htm", ".url", ".exe", ".bat", ".sh", ".apk",
             ".jpg", ".jpeg", ".png", ".gif", ".webp", ".nfo", ".doc", ".docx", ".pdf"}
PROMO_WORDS = ("预告", "花絮", "彩蛋", "访谈", "宣传片", "trailer", "teaser",
               "公众号", "扫码", "广告")
PART_RE = re.compile(r"(?:cd|disc|part|pt)[\s._-]*(\d{1,2})", re.I)


def _ext(name):
    idx = name.rfind(".")
    return name[idx:].lower() if idx > 0 else ""


def parse_season_episode(name):
    """从文件名解析 (季, 集)。解析不出返回 None。"""
    m = re.search(r"[Ss](\d{1,2})[\s._-]*[Ee](\d{1,3})", name)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"第\s*(\d{1,3})\s*[集话話]", name)
    if m:
        return 1, int(m.group(1))
    m = re.search(r"\bEP?\s*(\d{1,3})\b", name, re.I)
    if m:
        return 1, int(m.group(1))
    m = re.search(r"^(\d{1,3})(?:[\s._-]|$)", name)
    if m:
        return 1, int(m.group(1))
    m = re.search(r"[\s._【\[](\d{1,3})[\s._】\]]", name)
    if m:
        return 1, int(m.group(1))
    return None


def parse_season(name, default=1):
    m = re.search(r"[Ss](\d{1,2})[\s._-]*[Ee]\d", name)
    if m:
        return int(m.group(1))
    m = re.search(r"第\s*([一二三四五六七八九十\d]{1,3})\s*季", name)
    if m:
        zh = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        raw = m.group(1)
        return zh.get(raw, int(raw) if raw.isdigit() else default)
    return default


def parse_year(text):
    m = re.search(r"\b(19|20)\d{2}\b", text or "")
    return m.group(0) if m else ""


def quality_rank(name):
    """清晰度排序值，越大越好。只凭文件名标签推断。"""
    n = name.lower()
    if "2160p" in n or "4k" in n or "uhd" in n:
        return 4
    if "1080p" in n or "1080i" in n:
        return 3
    if "720p" in n:
        return 2
    if "480p" in n or "360p" in n:
        return 1
    return 0


def _is_promo(name):
    low = name.lower()
    return any(w.lower() in low for w in PROMO_WORDS)


def build_plan(files, title, kind, min_video_mb=30, candidate_title=""):
    """
    files: quark.share_walk 的拍平列表（只传文件，目录会被忽略）
    kind: "tv" | "movie"
    返回 plan dict: {keep:[...], skip:[...], warnings:[], total_size:int}
    keep 项: {src_fid, src_token, src_parent_fid, src_name, src_path, size,
              new_name, tag, season, episode}
    skip 项: {src_name, src_path, reason}
    """
    min_bytes = int(min_video_mb) * 1024 * 1024
    year = parse_year(candidate_title) or parse_year(title)
    keep, skip, warnings = [], [], []

    videos, subtitles, others = [], [], []
    for f in files:
        if f.get("dir"):
            continue
        ext = _ext(f["name"])
        item = {
            "src_fid": f["fid"], "src_token": f.get("token", ""),
            "src_parent_fid": f.get("parent_fid", "0"),
            "src_name": f["name"], "src_path": f.get("path", f["name"]),
            "size": f.get("size", 0) or 0, "ext": ext,
        }
        if ext in VIDEO_EXTS:
            videos.append(item)
        elif ext in SUBTITLE_EXTS:
            subtitles.append(item)
        elif ext in ARCHIVE_EXTS:
            item["tag"] = "archive"
            item["warn"] = "压缩包，无法挑内含物，整包保留"
            others.append(item)
        elif ext in JUNK_EXTS:
            skip.append({"src_name": f["name"], "src_path": item["src_path"],
                         "reason": "杂文件（" + (ext or "无扩展名") + "）"})
        else:
            item["tag"] = "other"
            item["warn"] = "未识别类型，默认保留"
            others.append(item)

    # ---- 视频：先剔小文件/推广，再按集分组去重 ----
    groups = {}
    for v in videos:
        if _is_promo(v["src_name"]):
            skip.append({"src_name": v["src_name"], "src_path": v["src_path"],
                         "reason": "疑似预告/花絮/推广（可在计划页勾回）"})
            continue
        if v["size"] and v["size"] < min_bytes:
            skip.append({"src_name": v["src_name"], "src_path": v["src_path"],
                         "reason": "体积过小（%.1fMB），疑似样片/广告" % (v["size"] / 1048576)})
            continue
        se = parse_season_episode(v["src_name"])
        part = PART_RE.search(v["src_name"])
        if kind == "tv":
            if se:
                key = ("ep", se[0], se[1])
                v["season"], v["episode"] = se
            else:
                key = ("unknown", v["src_name"])
                v["season"], v["episode"] = parse_season(v["src_name"]), None
                v["warn"] = "未能解析集号，默认保留"
        else:  # movie
            if part:
                key = ("part", int(part.group(1)))
                v["part"] = int(part.group(1))
            else:
                key = ("movie",)
            v["season"], v["episode"] = None, None
        groups.setdefault(key, []).append(v)

    kept_episodes = {}
    for key, group in groups.items():
        group.sort(key=lambda x: (quality_rank(x["src_name"]), x["size"]), reverse=True)
        best = group[0]
        best["tag"] = "video"
        keep.append(best)
        if key[0] == "ep":
            kept_episodes[(key[1], key[2])] = best
        for dup in group[1:]:
            skip.append({"src_name": dup["src_name"], "src_path": dup["src_path"],
                         "reason": "同集重复版本，已保留更优的「" + best["src_name"] + "」"})

    # ---- 字幕：按集配对 ----
    for s in subtitles:
        se = parse_season_episode(s["src_name"])
        s["tag"] = "subtitle"
        if se:
            s["season"], s["episode"] = se
            if (se[0], se[1]) not in kept_episodes and kind == "tv":
                s["warn"] = "对应集的视频未保留，字幕仍保留备查"
        keep.append(s)

    keep.extend(others)

    # ---- 生成新名字 ----
    for item in keep:
        ext = item["ext"]
        if item["tag"] == "video":
            if kind == "tv" and item.get("episode"):
                item["new_name"] = "%s.S%02dE%02d%s" % (title, item["season"], item["episode"], ext)
            elif kind == "movie" and item.get("part"):
                base = "%s (%s)" % (title, year) if year else title
                item["new_name"] = "%s.Part%d%s" % (base, item["part"], ext)
            elif kind == "movie":
                base = "%s (%s)" % (title, year) if year else title
                item["new_name"] = base + ext
            else:
                item["new_name"] = item["src_name"]
        elif item["tag"] == "subtitle":
            if kind == "tv" and item.get("episode"):
                item["new_name"] = "%s.S%02dE%02d%s" % (title, item["season"], item["episode"], ext)
            else:
                item["new_name"] = item["src_name"]
        else:
            item["new_name"] = item["src_name"]

    # ---- 缺集检查（电视剧） ----
    if kind == "tv" and kept_episodes:
        by_season = {}
        for (season, ep) in kept_episodes:
            by_season.setdefault(season, set()).add(ep)
        for season, eps in sorted(by_season.items()):
            missing = [e for e in range(min(eps), max(eps) + 1) if e not in eps]
            if missing:
                warnings.append("第 %d 季缺集：%s" % (season, ", ".join("E%02d" % e for e in missing)))

    keep.sort(key=lambda x: (x.get("season") or 0, x.get("episode") or 0, x["src_name"]))
    total = sum(x["size"] for x in keep)
    return {"keep": keep, "skip": skip, "warnings": warnings, "total_size": total}
