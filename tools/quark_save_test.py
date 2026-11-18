#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
夸克转存接口一次性验证脚本（只用 Python 标准库，无需 pip 安装任何东西）

验证目标（在部署机本地跑）：
  1) 一份夸克 Cookie 能否调通夸克接口（列根目录）
  2) 分享链接能否换到 stoken 并列出文件
  3) 保存到指定文件夹的任务能否跑完、文件是否真落盘

用法：
  先把 Cookie 存成本脚本同目录下的 cookie.txt（只有一行，权限 600），然后：

  python3 quark_save_test.py list
      列出夸克根目录的文件夹和 fid，找到（或确认）测试文件夹的 fid

  python3 quark_save_test.py save <分享链接> <目标文件夹fid> [提取码]
      例：python3 quark_save_test.py save https://pan.quark.cn/s/xxxxxxxxxxxx 5f3a...  1234
      目标 fid 填 0 表示存到根目录（不建议，仅兜底）

注意：脚本全程不打印 Cookie，只打印每一步的成败和关键字段。
失败时把完整输出发回给维护者看（输出里没有任何凭证），不要发 cookie.txt。
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

BASE = "https://drive-h.quark.cn/1/clouddrive"
COMMON = {"pr": "ucpro", "fr": "pc", "uc_param_str": ""}

HERE = os.path.dirname(os.path.abspath(__file__))


def load_cookie():
    env = os.environ.get("QUARK_COOKIE", "").strip()
    if env:
        return env
    path = os.path.join(HERE, "cookie.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    print("FAIL: 找不到 Cookie。请把 Cookie 存为脚本同目录的 cookie.txt，或设置环境变量 QUARK_COOKIE")
    sys.exit(1)


COOKIE = load_cookie()

HEADERS = {
    "Cookie": COOKIE,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://pan.quark.cn/",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
}


def call(method, path, params=None, body=None):
    q = dict(COMMON)
    if params:
        q.update(params)
    url = BASE + path + "?" + urllib.parse.urlencode(q)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:500]}
    except Exception as e:
        return 0, {"error": str(e)}


def check(resp, step):
    status, payload = resp
    code = payload.get("code")
    ok = status == 200 and (code in (0, "0", None))
    print(f"[{step}] HTTP {status} code={code} message={payload.get('message') or payload.get('msg') or ''}")
    if not ok:
        print(f"[{step}] 原始返回（截断）: {json.dumps(payload, ensure_ascii=False)[:800]}")
    return ok, payload.get("data") or {}


def list_dir(pdir_fid="0"):
    ok, data = check(call("GET", "/file/sort", {
        "pdir_fid": pdir_fid, "_page": 1, "_size": 100,
        "_sort": "file_type:asc,file_name:asc",
    }), "STEP1 列目录")
    if not ok:
        print("结论：Cookie 无效或已过期（连自己的目录都列不出来），先换一份新 Cookie 再测。")
        return False
    items = data.get("list", [])
    print(f"根目录共 {len(items)} 项：")
    for it in items:
        kind = "DIR " if it.get("dir") else "FILE"
        print(f"  [{kind}] fid={it.get('fid')}  {it.get('file_name')}")
    print("STEP1 OK：Cookie 有效，能调通夸克接口。记下测试文件夹的 fid，下一步要用。")
    return True


def parse_share(url):
    m = re.search(r"pan\.quark\.cn/s/([0-9a-zA-Z]+)", url)
    if not m:
        print("FAIL: 分享链接里解析不出分享 ID，应形如 https://pan.quark.cn/s/xxxx")
        sys.exit(1)
    pwd_id = m.group(1)
    passcode = ""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    if "pwd" in q:
        passcode = q["pwd"][0]
    return pwd_id, passcode


def do_save(share_url, to_fid, passcode_arg=""):
    pwd_id, passcode = parse_share(share_url)
    if passcode_arg:
        passcode = passcode_arg
    print(f"分享 ID: {pwd_id}，提取码: {'(有)' if passcode else '(无)'}，目标 fid: {to_fid}")

    ok, data = check(call("POST", "/share/sharepage/token", {},
                          {"pwd_id": pwd_id, "passcode": passcode}), "STEP2 换 stoken")
    if not ok:
        print("结论：换不到 stoken。多为链接已失效、分享被取消，或提取码不对——换一条链接再测。")
        return False
    stoken = data.get("stoken", "")
    print(f"STEP2 OK：拿到 stoken（长度 {len(stoken)}）")
    if not stoken:
        print("结论：返回里没有 stoken，接口形态可能已变，把输出发给维护者看。")
        return False

    ok, data = check(call("GET", "/share/sharepage/detail", {
        "pwd_id": pwd_id, "stoken": stoken, "pdir_fid": "0",
        "_page": 1, "_size": 100, "_sort": "file_type:asc,file_name:asc",
    }), "STEP3 列分享文件")
    if not ok:
        print("结论：stoken 有了但列不出分享内容，把输出发给维护者看。")
        return False
    items = data.get("list", [])
    if not items:
        print("结论：分享里是空的，换一条链接再测。")
        return False
    print(f"STEP3 OK：分享顶层共 {len(items)} 项：")
    for it in items:
        kind = "DIR " if it.get("dir") else "FILE"
        print(f"  [{kind}] {it.get('file_name')}")
    fid_list = [it["fid"] for it in items]
    token_list = [it.get("share_fid_token", "") for it in items]

    ok, data = check(call("POST", "/share/sharepage/save", {}, {
        "fid_list": fid_list,
        "fid_token_list": token_list,
        "to_pdir_fid": to_fid,
        "pwd_id": pwd_id,
        "stoken": stoken,
        "pdir_fid": "0",
        "scene": "link",
    }), "STEP4 提交保存")
    if not ok:
        print("结论：保存请求被拒，看上面 message（常见：容量不足、目标文件夹不存在、分享方限制）。")
        return False
    task_id = data.get("task_id", "")
    print(f"STEP4 OK：保存任务已提交 task_id={task_id}")
    if not task_id:
        print("没有 task_id，可能已同步完成，直接去目标文件夹核对。")
        return True

    for i in range(60):
        time.sleep(2)
        ok, data = check(call("GET", "/task", {
            "task_id": task_id, "retry_index": i,
        }), f"STEP5 轮询任务 第{i + 1}次")
        st = data.get("status")
        print(f"  任务状态 status={st}")
        if st == 2:
            print("STEP5 OK：夸克侧报告转存完成。")
            return True
        if st in (3, 4) or (isinstance(st, int) and st > 4):
            print(f"结论：任务终态异常 status={st}，把输出发给维护者看。")
            return False
    print("结论：轮询 120 秒未完成，可能还在排队，去夸克里看目标文件夹确认，别重复提交。")
    return False


def main():
    print(f"Cookie 已加载（长度 {len(COOKIE)}，不显示内容）")
    if len(sys.argv) >= 2 and sys.argv[1] == "list":
        list_dir()
    elif len(sys.argv) >= 4 and sys.argv[1] == "save":
        ok = do_save(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) >= 5 else "")
        print("==== 测试结论:", "通过 ✅ 转存链路可用" if ok else "未通过 ❌ 按上面结论处理", "====")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
