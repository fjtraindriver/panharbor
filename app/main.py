# -*- coding: utf-8 -*-
"""
PanHarbor 主服务：零第三方依赖（Python 标准库 http.server），
保证 docker build 不受包源影响。

环境变量：
  DATA_DIR     数据目录（默认 /data，本地调试可改）
  APP_PASSWORD 初始访问密码（默认 panharbor，设置页改密后以库内哈希为准）
  PORT         容器内监听端口（默认 8080）
"""

import hashlib
import json
import os
import random
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import store, executor, planner
from .pansou import PansouClient, PansouError
from .quark import QuarkClient, QuarkError

DATA_DIR = os.environ.get("DATA_DIR", "/data")
PORT = int(os.environ.get("PORT", "8080"))
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

_sessions = {}  # token -> 过期时间戳（内存会话，重启需重新登录，单用户可接受）


def _password_hash():
    saved = store.get_setting("app_password_hash")
    if saved:
        return saved
    return hashlib.sha256(os.environ.get("APP_PASSWORD", "panharbor").encode()).hexdigest()


def _check_password(pw):
    return hashlib.sha256((pw or "").encode()).hexdigest() == _password_hash()


def _quark():
    return QuarkClient(store.get_setting("quark_cookie"),
                       on_cookie_update=store.setting_updater("quark_cookie"))


# ---------- 夸克 Cookie 保活 ----------
# Cookie 靠服务端 Set-Cookie 轮换续期（见 quark.py）：只要定期有一次成功请求，
# 新值就会被吸收并写回库里。保活线程每 24 小时列一次根目录，另加 0~3 小时
# 随机抖动，避免固定时间点的机械特征；频率再高没有收益，还有风控风险。
KEEPALIVE_INTERVAL = 24 * 3600
KEEPALIVE_JITTER = 3 * 3600
KEEPALIVE_FIRST_DELAY = (120, 600)  # 启动后先等 2~10 分钟再首次保活


def _keepalive_delay():
    return KEEPALIVE_INTERVAL + random.uniform(0, KEEPALIVE_JITTER)


def _keepalive_once():
    """跑一次保活，结果记进 settings 供状态页展示。返回是否成功。"""
    if not store.get_setting("quark_cookie"):
        return False
    try:
        _quark().list_dir("0", size=1, max_pages=1)
        ok, msg = True, "Cookie 有效"
    except Exception as e:
        ok, msg = False, str(e)[:200]
    store.set_setting("quark_keepalive_at", str(int(time.time())))
    store.set_setting("quark_keepalive_ok", "1" if ok else "0")
    store.set_setting("quark_keepalive_msg", msg)
    return ok


def _keepalive_loop():
    time.sleep(random.uniform(*KEEPALIVE_FIRST_DELAY))
    while True:
        try:
            _keepalive_once()
        except Exception:
            pass  # 保活线程绝不能因一次异常退出
        time.sleep(_keepalive_delay())


def _pansou():
    return PansouClient(store.get_setting("pansou_base"),
                        store.get_setting("pansou_username"),
                        store.get_setting("pansou_password"))


class Handler(BaseHTTPRequestHandler):
    server_version = "PanHarbor/0.3"

    # ---------- 工具 ----------
    def log_message(self, fmt, *args):  # 静音默认访问日志，排障看任务日志
        pass

    def _send_json(self, obj, status=200, headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self._send_json({"error": "not found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _authed(self):
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("ph_session="):
                token = part[len("ph_session="):]
                exp = _sessions.get(token, 0)
                if exp > time.time():
                    return True
                _sessions.pop(token, None)
        return False

    # ---------- 路由 ----------
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            return self._send_file(os.path.join(STATIC_DIR, "index.html"),
                                   "text/html; charset=utf-8")
        if path == "/app.js":
            return self._send_file(os.path.join(STATIC_DIR, "app.js"),
                                   "application/javascript; charset=utf-8")
        if path == "/favicon.svg":
            return self._send_file(os.path.join(STATIC_DIR, "favicon.svg"),
                                   "image/svg+xml; charset=utf-8")
        if path == "/favicon.ico":
            ico = os.path.join(STATIC_DIR, "favicon.ico")
            if os.path.exists(ico):
                return self._send_file(ico, "image/x-icon")
            # 图标二进制不在当前部署里时，用 SVG 兜底（现代浏览器可识别）
            return self._send_file(os.path.join(STATIC_DIR, "favicon.svg"),
                                   "image/svg+xml; charset=utf-8")
        if path == "/style.css":
            return self._send_file(os.path.join(STATIC_DIR, "style.css"),
                                   "text/css; charset=utf-8")
        if not path.startswith("/api/"):
            return self._send_json({"error": "not found"}, 404)
        if not self._authed():
            return self._send_json({"error": "未登录"}, 401)
        try:
            if path == "/api/tasks":
                return self._send_json({"tasks": store.list_tasks()})
            if path.startswith("/api/tasks/"):
                task = store.get_task(int(path.rsplit("/", 1)[1]))
                return self._send_json({"task": task} if task else {"error": "任务不存在"}, 200 if task else 404)
            if path == "/api/settings":
                return self._send_json({"settings": self._public_settings()})
            if path == "/api/quark/folders":
                qs = parse_qs(urlparse(self.path).query)
                fid = (qs.get("fid") or ["0"])[0]
                items = _quark().list_dir(fid)
                dirs = [{"fid": i["fid"], "name": i["file_name"]}
                        for i in items if i.get("dir")]
                return self._send_json({"folders": dirs})
            if path == "/api/status":
                return self._send_json(self._status())
            return self._send_json({"error": "not found"}, 404)
        except (QuarkError, PansouError) as e:
            return self._send_json({"error": str(e)}, 502)
        except Exception as e:
            return self._send_json({"error": f"服务异常: {e}"}, 500)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_json()
        if path == "/api/login":
            if _check_password(body.get("password", "")):
                token = secrets.token_urlsafe(32)
                _sessions[token] = time.time() + 7 * 24 * 3600
                return self._send_json(
                    {"ok": True},
                    headers={"Set-Cookie": f"ph_session={token}; Path=/; HttpOnly; Max-Age=604800"})
            return self._send_json({"error": "密码不对"}, 403)
        if not path.startswith("/api/"):
            return self._send_json({"error": "not found"}, 404)
        if not self._authed():
            return self._send_json({"error": "未登录"}, 401)
        try:
            if path == "/api/logout":
                _sessions.clear()
                return self._send_json({"ok": True})
            if path == "/api/settings":
                return self._save_settings(body)
            if path == "/api/settings/password":
                store.set_setting("app_password_hash",
                                  hashlib.sha256(body.get("password", "").encode()).hexdigest())
                return self._send_json({"ok": True})
            if path == "/api/verify/quark":
                items = _quark().list_dir("0", size=50)
                dirs = [{"fid": i["fid"], "name": i["file_name"]}
                        for i in items if i.get("dir")]
                return self._send_json({"ok": True, "root_folders": dirs})
            if path == "/api/verify/pansou":
                ok, msg = _pansou().ping()
                return self._send_json({"ok": ok, "message": msg})
            if path == "/api/search":
                return self._search(body)
            if path == "/api/plan":
                return self._plan(body)
            if path == "/api/execute":
                return self._execute(body)
            return self._send_json({"error": "not found"}, 404)
        except (QuarkError, PansouError) as e:
            return self._send_json({"error": str(e)}, 502)
        except Exception as e:
            return self._send_json({"error": f"服务异常: {e}"}, 500)

    # ---------- 业务 ----------
    def _public_settings(self):
        cookie = store.get_setting("quark_cookie")
        return {
            "pansou_base": store.get_setting("pansou_base"),
            "pansou_username": store.get_setting("pansou_username"),
            "has_pansou_password": bool(store.get_setting("pansou_password")),
            "has_quark_cookie": bool(cookie),
            "quark_cookie_tail": cookie[-4:] if cookie else "",
            "movie_fid": store.get_setting("movie_fid"),
            "tv_fid": store.get_setting("tv_fid"),
            "movie_name": store.get_setting("movie_name"),
            "tv_name": store.get_setting("tv_name"),
            "min_video_mb": store.get_setting("min_video_mb", "30"),
            "check_limit": store.get_setting("check_limit", "10"),
            "check_alive": store.get_setting("check_alive", "1"),
        }

    def _save_settings(self, body):
        simple = ("pansou_base", "pansou_username", "movie_fid", "tv_fid",
                  "movie_name", "tv_name", "min_video_mb", "check_limit", "check_alive")
        for key in simple:
            if key in body:
                store.set_setting(key, str(body[key]))
        if body.get("pansou_password"):
            store.set_setting("pansou_password", body["pansou_password"])
        if body.get("quark_cookie"):
            store.set_setting("quark_cookie", body["quark_cookie"].strip())
        return self._send_json({"ok": True, "settings": self._public_settings()})

    def _status(self):
        out = {}
        try:
            ok, msg = _pansou().ping()
            out["pansou"] = {"ok": ok, "message": msg}
        except Exception as e:
            out["pansou"] = {"ok": False, "message": str(e)}
        try:
            _quark().list_dir("0", size=1, max_pages=1)
            out["quark"] = {"ok": True, "message": "Cookie 有效"}
        except Exception as e:
            out["quark"] = {"ok": False, "message": str(e)}
        ka_at = store.get_setting("quark_keepalive_at")
        out["keepalive"] = {
            "at": int(ka_at) if ka_at.isdigit() else None,
            "ok": (store.get_setting("quark_keepalive_ok") == "1") if ka_at else None,
            "message": store.get_setting("quark_keepalive_msg"),
        }
        tasks = store.list_tasks(100)
        out["tasks"] = {
            "total": len(tasks),
            "done": sum(1 for t in tasks if t["status"] == "done"),
            "failed": sum(1 for t in tasks if t["status"] == "failed"),
        }
        return out

    def _search(self, body):
        kw = (body.get("kw") or "").strip()
        if not kw:
            return self._send_json({"error": "片名不能为空"}, 400)
        candidates = _pansou().search(kw)
        # 验活（可关）：用夸克 Cookie 逐条轻量验，只验前 N 条
        if store.get_setting("check_alive", "1") == "1" and store.get_setting("quark_cookie"):
            limit = int(store.get_setting("check_limit", "10") or 10)
            client = _quark()
            for idx, cand in enumerate(candidates):
                if idx >= limit:
                    cand["alive"] = None
                    continue
                alive, top = client.check_share_alive(cand["url"], cand.get("password", ""))
                cand["alive"] = alive
                cand["top_count"] = len(top)
        else:
            for cand in candidates:
                cand["alive"] = None
        return self._send_json({"candidates": candidates})

    def _plan(self, body):
        url = body.get("url") or ""
        title = (body.get("title") or "").strip()
        kind = body.get("kind") or "tv"
        if not title:
            return self._send_json({"error": "片名不能为空"}, 400)
        client = _quark()
        pwd_id = client.parse_share_id(url)
        if not pwd_id:
            return self._send_json({"error": "分享链接解析不出 ID"}, 400)
        stoken = client.share_token(pwd_id, body.get("password", ""))
        files = client.share_walk(pwd_id, stoken)
        plan = planner.build_plan(files, title, kind,
                                  min_video_mb=int(store.get_setting("min_video_mb", "30") or 30),
                                  candidate_title=body.get("candidate_title", ""))
        plan["pwd_id"] = pwd_id
        plan["passcode"] = body.get("password", "")
        plan["url"] = url
        return self._send_json({"plan": plan})

    def _execute(self, body):
        plan = body.get("plan") or {}
        title = (body.get("title") or "").strip()
        kind = body.get("kind") or "tv"
        if not plan.get("keep"):
            return self._send_json({"error": "计划里没有要存的文件"}, 400)
        # 前端可在计划页增减勾选，这里以最终提交的 keep 为准
        task_id = store.create_task(title, kind)
        store.update_task(task_id, status="queued")
        executor.start_task(task_id, plan, title, kind)
        return self._send_json({"ok": True, "task_id": task_id})


def main():
    store.init(DATA_DIR)
    threading.Thread(target=_keepalive_loop, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"PanHarbor listening on :{PORT}, data dir {DATA_DIR}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
