# -*- coding: utf-8 -*-
"""
任务执行器：按计划把文件转存进目标目录，再改名、验收。
在后台线程里跑，进度写回任务记录，前端轮询任务状态即可。

流程：建干净文件夹 → 按源父目录分组提交保存 → 轮询 → 列目录对名改名 → 验收比对。
嵌套子目录文件的按 fid 直存（蓝图验证项 V2）若被夸克拒绝，该组会记为失败、
任务标 partial，不影响其它组；不会静默吞错。
"""

import threading

from . import store
from .quark import QuarkClient, QuarkError


def start_task(task_id, plan, title, kind):
    t = threading.Thread(target=_run, args=(task_id, plan, title, kind), daemon=True)
    t.start()
    return t


def _run(task_id, plan, title, kind):
    detail = {"log": [], "plan_keep": len(plan.get("keep", [])),
              "plan_skip": len(plan.get("skip", []))}

    def log(msg):
        detail["log"].append(msg)
        store.update_task(task_id, detail=detail)

    try:
        cookie = store.get_setting("quark_cookie")
        client = QuarkClient(cookie)
        parent_fid = store.get_setting("movie_fid" if kind == "movie" else "tv_fid")
        if not parent_fid:
            raise QuarkError("设置里还没选目标目录（电影/电视剧文件夹）")

        store.update_task(task_id, status="saving", detail=detail)

        # 1) 目标文件夹：同名存在就复用（顺带支持增量补集）
        existing = client.find_child(parent_fid, title)
        if existing:
            folder_fid = existing["fid"]
            log(f"复用已有文件夹「{title}」")
        else:
            folder_fid = client.mkdir(parent_fid, title)
            log(f"已新建文件夹「{title}」")

        # 2) 已存在的同名文件跳过（防重复转存）
        present = {it["file_name"] for it in client.list_dir(folder_fid)}
        todo = []
        for item in plan["keep"]:
            if item["new_name"] in present or item["src_name"] in present:
                log(f"跳过（已存在）：{item['new_name']}")
            else:
                todo.append(item)

        # 3) 按源父目录分组提交保存
        groups = {}
        for item in todo:
            groups.setdefault(item["src_parent_fid"], []).append(item)
        failed_groups = 0
        for parent, items in groups.items():
            try:
                # 先换一份新鲜 stoken 再存（计划生成到执行可能隔了一段时间）
                pwd_id = plan["pwd_id"]
                stoken = client.share_token(pwd_id, plan.get("passcode", ""))
                task_id_remote = client.save(
                    pwd_id, stoken,
                    [i["src_fid"] for i in items],
                    [i["src_token"] for i in items],
                    folder_fid, pdir_fid=parent)
                if task_id_remote:
                    client.wait_task(task_id_remote)
                log(f"已保存 {len(items)} 个文件（源目录组 {parent[:8]}…）")
            except QuarkError as e:
                failed_groups += 1
                log(f"一组文件保存失败（源目录组 {parent[:8]}…）：{e}")

        # 4) 改名：按原名在目标文件夹里找到文件，改成规范名
        store.update_task(task_id, status="renaming", detail=detail)
        by_old_name = {}
        for it in client.list_dir(folder_fid):
            by_old_name.setdefault(it["file_name"], it)
        renamed, rename_failed = 0, 0
        for item in todo:
            target = by_old_name.get(item["src_name"])
            if not target:
                continue
            if item["new_name"] == item["src_name"]:
                continue
            if item["new_name"] in by_old_name:
                log(f"改名跳过（目标名已存在）：{item['new_name']}")
                continue
            try:
                client.rename(target["fid"], item["new_name"])
                renamed += 1
            except QuarkError as e:
                rename_failed += 1
                log(f"改名失败 {item['src_name']} → {item['new_name']}：{e}")
        log(f"改名完成：{renamed} 个，失败 {rename_failed} 个")

        # 5) 验收：实际落盘 vs 计划
        store.update_task(task_id, status="verifying", detail=detail)
        final_names = {it["file_name"] for it in client.list_dir(folder_fid)}
        expected = {i["new_name"] for i in plan["keep"]}
        missing = sorted(n for n in expected if n not in final_names)
        detail["result"] = {
            "folder": title,
            "expected": len(expected),
            "present": len(expected) - len(missing),
            "missing": missing,
            "warnings": plan.get("warnings", []),
        }
        if failed_groups or missing or rename_failed:
            store.update_task(task_id, status="partial", detail=detail)
            log("任务结束：部分完成，详见结果")
        else:
            store.update_task(task_id, status="done", detail=detail)
            log("任务结束：全部完成")
    except QuarkError as e:
        detail["error"] = str(e)
        store.update_task(task_id, status="failed", detail=detail)
    except Exception as e:  # 兜底：任何异常都落到任务记录里，不让线程静默死
        detail["error"] = f"未预期异常: {e}"
        store.update_task(task_id, status="failed", detail=detail)
