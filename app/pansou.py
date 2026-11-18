# -*- coding: utf-8 -*-
"""
pansou 搜索客户端（搜索源之一）。

通过配置的 pansou 服务地址访问（可直连后端，或经反向代理中转到后端）。
若 pansou 开了 JWT 认证：POST /api/auth/login 换 token，请求带 Bearer。
"""

import json
import time
import urllib.request
import urllib.error


class PansouError(Exception):
    pass


def _find_token(payload):
    """在登录返回里递归找 token 字段（不同版本字段位置可能不同）。"""
    if isinstance(payload, dict):
        for key in ("token", "access_token", "accessToken"):
            val = payload.get(key)
            if isinstance(val, str) and val:
                return val
        for val in payload.values():
            found = _find_token(val)
            if found:
                return found
    return None


class PansouClient:
    def __init__(self, base, username="", password=""):
        self.base = (base or "").rstrip("/")
        if not self.base:
            raise PansouError("未配置 pansou 地址")
        self.username = username or ""
        self.password = password or ""
        self._token = None
        self._token_at = 0

    def _request(self, method, path, body=None, auth=True):
        url = self.base + path
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if auth and self._token:
            headers["Authorization"] = "Bearer " + self._token
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "ignore")
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"raw": raw[:300]}
        except Exception as e:
            raise PansouError(f"访问 pansou 失败: {e}")

    def login(self):
        if not self.username:
            self._token = None
            return False
        status, payload = self._request("POST", "/api/auth/login",
                                        {"username": self.username, "password": self.password},
                                        auth=False)
        token = _find_token(payload)
        if not token:
            msg = payload.get("error") or payload.get("message") or f"HTTP {status}"
            raise PansouError(f"pansou 登录失败: {msg}")
        self._token = token
        self._token_at = time.time()
        return True

    def _ensure_token(self):
        if self.username and (not self._token or time.time() - self._token_at > 3600):
            self.login()

    def ping(self):
        """状态页用：能登录（或匿名能调 health）即视为可达。"""
        try:
            if self.username:
                self.login()
                return True, "登录成功"
            status, _ = self._request("GET", "/api/health", auth=False)
            return status == 200, f"health HTTP {status}"
        except PansouError as e:
            return False, str(e)

    def search(self, kw, cloud_types=("quark",)):
        """返回去重后的候选列表：[{url, password, title, datetime, source}]"""
        self._ensure_token()
        body = {
            "kw": kw,
            "cloud_types": list(cloud_types),
            "res": "merge",
            "src": "all",
        }
        status, payload = self._request("POST", "/api/search", body)
        # 令牌过期/未带令牌时重登一次再试
        code = str(payload.get("code", ""))
        if status in (401, 403) or "AUTH" in code:
            if self.username:
                self.login()
                status, payload = self._request("POST", "/api/search", body)
        if status != 200:
            msg = payload.get("error") or payload.get("message") or f"HTTP {status}"
            raise PansouError(f"pansou 搜索失败: {msg}")
        return self._normalize(payload)

    @staticmethod
    def _normalize(payload):
        data = payload.get("data") or {}
        raw_items = []
        if isinstance(data, dict):
            merged = data.get("merged_by_type") or {}
            if isinstance(merged, dict):
                for cloud in ("quark",):
                    raw_items.extend(merged.get(cloud) or [])
            if not raw_items and isinstance(data.get("results"), list):
                raw_items = [r for r in data["results"]
                             if (r.get("type") or r.get("cloud_type")) in (None, "quark")]
        elif isinstance(data, list):
            raw_items = data
        seen = set()
        out = []
        for it in raw_items:
            if not isinstance(it, dict):
                continue
            url = it.get("url") or it.get("link") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            out.append({
                "url": url,
                "password": it.get("password") or it.get("passcode") or "",
                "title": it.get("note") or it.get("title") or it.get("name") or "",
                "datetime": it.get("datetime") or it.get("time") or "",
                "source": it.get("source") or it.get("channel") or "",
            })
        return out
