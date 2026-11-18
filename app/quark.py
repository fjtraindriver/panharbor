# -*- coding: utf-8 -*-
"""
夸克网盘客户端（网盘驱动之一）。

接口形态来自开源实现（AList 夸克驱动 / quark-auto-save）并已实测通过五步：
列目录、换 stoken、列分享、提交保存、轮询任务。
建文件夹 / 改名接口与上面同族，待 V3 扩展验证（失败会抛 QuarkError，
上层会把原始信息写入任务日志，不会静默吞掉）。

Cookie 续期：夸克会通过响应的 Set-Cookie 轮换部分字段（典型是 __puus），
新值不回写的话旧 Cookie 迟早失效。本客户端每次请求后都会吸收 Set-Cookie，
合并出新 Cookie 后经 on_cookie_update 回调交给上层持久化。
"""

import json
import time
import urllib.parse
import urllib.request
import urllib.error

BASE = "https://drive-h.quark.cn/1/clouddrive"
COMMON = {"pr": "ucpro", "fr": "pc", "uc_param_str": ""}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class QuarkError(Exception):
    def __init__(self, message, payload=None, status=None):
        super().__init__(message)
        self.payload = payload
        self.status = status


def parse_cookie(cookie):
    """把 Cookie 字符串解析成有序的 [(name, value)]，跳过坏段。"""
    pairs = []
    for part in (cookie or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name:
            pairs.append((name, value.strip()))
    return pairs


def merge_set_cookies(cookie, set_cookie_headers):
    """把响应 Set-Cookie 的新值合并进 Cookie 字符串。

    每个 Set-Cookie 只取第一个 ; 前的 name=value（其余是 expires/path 等属性）。
    值为空视为服务端删除该字段。没有实际变化时原样返回。
    """
    pairs = parse_cookie(cookie)
    index = {name: i for i, (name, _) in enumerate(pairs)}
    changed = False
    for header in set_cookie_headers or []:
        first = (header or "").split(";", 1)[0].strip()
        if not first or "=" not in first:
            continue
        name, value = first.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name:
            continue
        if not value:
            if name in index:
                pairs[index[name]] = (name, None)
                changed = True
            continue
        if name in index:
            if pairs[index[name]][1] != value:
                pairs[index[name]] = (name, value)
                changed = True
        else:
            index[name] = len(pairs)
            pairs.append((name, value))
            changed = True
    if not changed:
        return cookie
    return "; ".join(f"{n}={v}" for n, v in pairs if v is not None)


class QuarkClient:
    def __init__(self, cookie, on_cookie_update=None):
        self.cookie = (cookie or "").strip()
        if not self.cookie:
            raise QuarkError("未配置夸克 Cookie")
        self._on_cookie_update = on_cookie_update

    def _absorb_set_cookies(self, headers):
        """吸收响应里的 Set-Cookie 轮换值，变了就更新自身并回调上层持久化。"""
        if headers is None:
            return
        try:
            values = headers.get_all("Set-Cookie") or []
        except Exception:
            return
        if not values:
            return
        merged = merge_set_cookies(self.cookie, values)
        if merged != self.cookie:
            self.cookie = merged
            if self._on_cookie_update:
                try:
                    self._on_cookie_update(merged)
                except Exception:
                    pass  # 持久化失败不打断本次请求，下次请求还会再吸收

    # ---------- 基础请求 ----------
    def _call(self, method, path, params=None, body=None):
        q = dict(COMMON)
        if params:
            q.update(params)
        url = BASE + path + "?" + urllib.parse.urlencode(q)
        headers = {
            "Cookie": self.cookie,
            "User-Agent": UA,
            "Referer": "https://pan.quark.cn/",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
        }
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self._absorb_set_cookies(resp.headers)
                payload = json.loads(resp.read().decode("utf-8"))
                status = resp.status
        except urllib.error.HTTPError as e:
            self._absorb_set_cookies(getattr(e, "headers", None))
            raw = e.read().decode("utf-8", "ignore")
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"raw": raw[:500]}
            status = e.code
        except Exception as e:
            raise QuarkError(f"网络请求失败: {e}")
        code = payload.get("code")
        if status != 200 or code not in (0, "0", None):
            msg = payload.get("message") or payload.get("msg") or f"HTTP {status} code={code}"
            raise QuarkError(str(msg), payload=payload, status=status)
        return payload.get("data") or {}

    # ---------- 自有网盘 ----------
    def list_dir(self, pdir_fid="0", size=100, max_pages=5):
        """列某个文件夹下的全部条目（自动翻页）。"""
        items = []
        for page in range(1, max_pages + 1):
            data = self._call("GET", "/file/sort", {
                "pdir_fid": pdir_fid, "_page": page, "_size": size,
                "_sort": "file_type:asc,file_name:asc",
            })
            batch = data.get("list", [])
            items.extend(batch)
            total = (data.get("metadata") or {}).get("_total") or len(items)
            if len(items) >= total or not batch:
                break
        return items

    def find_child(self, pdir_fid, name):
        for it in self.list_dir(pdir_fid):
            if it.get("file_name") == name:
                return it
        return None

    def mkdir(self, pdir_fid, name):
        data = self._call("POST", "/file", {}, {
            "pdir_fid": pdir_fid,
            "file_name": name,
            "dir_path": "",
            "dir_init_lock": False,
        })
        fid = data.get("fid")
        if not fid:
            found = self.find_child(pdir_fid, name)
            if found:
                return found.get("fid")
            raise QuarkError("建文件夹成功但没拿到 fid", payload=data)
        return fid

    def rename(self, fid, new_name):
        self._call("POST", "/file/rename", {}, {"fid": fid, "file_name": new_name})
        return True

    # ---------- 分享 ----------
    @staticmethod
    def parse_share_id(url):
        import re
        m = re.search(r"pan\.quark\.cn/s/([0-9a-zA-Z]+)", url or "")
        return m.group(1) if m else None

    def share_token(self, pwd_id, passcode=""):
        data = self._call("POST", "/share/sharepage/token", {},
                          {"pwd_id": pwd_id, "passcode": passcode or ""})
        stoken = data.get("stoken")
        if not stoken:
            raise QuarkError("换 stoken 失败：返回里没有 stoken", payload=data)
        return stoken

    def share_detail(self, pwd_id, stoken, pdir_fid="0", size=100, max_pages=10):
        items = []
        for page in range(1, max_pages + 1):
            data = self._call("GET", "/share/sharepage/detail", {
                "pwd_id": pwd_id, "stoken": stoken, "pdir_fid": pdir_fid,
                "_page": page, "_size": size,
                "_sort": "file_type:asc,file_name:asc",
            })
            batch = data.get("list", [])
            items.extend(batch)
            total = (data.get("metadata") or {}).get("_total") or len(items)
            if len(items) >= total or not batch:
                break
        return items

    def share_walk(self, pwd_id, stoken, max_entries=1000):
        """递归列出分享内全部条目，返回拍平列表（含父目录 fid 与相对路径）。"""
        result = []
        queue = [("0", "")]
        while queue:
            parent_fid, parent_path = queue.pop(0)
            for it in self.share_detail(pwd_id, stoken, parent_fid):
                path = (parent_path + "/" + it.get("file_name", "")).strip("/")
                result.append({
                    "fid": it.get("fid"),
                    "token": it.get("share_fid_token", ""),
                    "name": it.get("file_name", ""),
                    "dir": bool(it.get("dir")),
                    "size": it.get("size", 0) or 0,
                    "parent_fid": parent_fid,
                    "path": path,
                })
                if len(result) >= max_entries:
                    return result
                if it.get("dir"):
                    queue.append((it.get("fid"), path))
        return result

    def check_share_alive(self, url, passcode=""):
        """轻量验活：能换 stoken 且能列出顶层文件即视为活。返回 (alive, top_items)。"""
        pwd_id = self.parse_share_id(url)
        if not pwd_id:
            return False, []
        try:
            stoken = self.share_token(pwd_id, passcode)
            items = self.share_detail(pwd_id, stoken, "0", size=20, max_pages=1)
            return len(items) > 0, items
        except QuarkError:
            return False, []

    # ---------- 转存 ----------
    def save(self, pwd_id, stoken, fid_list, token_list, to_pdir_fid, pdir_fid="0"):
        data = self._call("POST", "/share/sharepage/save", {}, {
            "fid_list": fid_list,
            "fid_token_list": token_list,
            "to_pdir_fid": to_pdir_fid,
            "pwd_id": pwd_id,
            "stoken": stoken,
            "pdir_fid": pdir_fid,
            "scene": "link",
        })
        return data.get("task_id")

    def task_status(self, task_id, retry_index=0):
        data = self._call("GET", "/task", {"task_id": task_id, "retry_index": retry_index})
        return data.get("status"), data

    def wait_task(self, task_id, timeout=180, interval=2):
        """轮询保存任务。status==2 为完成；超时抛错（不等于失败，上层会提示人工核对）。"""
        waited = 0
        retry = 0
        while waited <= timeout:
            status, _ = self.task_status(task_id, retry)
            retry += 1
            if status == 2:
                return True
            if isinstance(status, int) and status >= 3:
                raise QuarkError(f"转存任务终态异常 status={status}")
            time.sleep(interval)
            waited += interval
        raise QuarkError(f"转存任务轮询 {timeout}s 未完成（可能仍在夸克侧排队，请勿重复提交）")
