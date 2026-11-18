# -*- coding: utf-8 -*-
"""SQLite 存储：设置（键值）与任务记录。单文件，放在数据卷里。"""

import json
import os
import sqlite3
import threading
import time

_lock = threading.Lock()
_conn = None


def init(data_dir):
    global _conn
    os.makedirs(data_dir, exist_ok=True)
    _conn = sqlite3.connect(os.path.join(data_dir, "panharbor.db"),
                            check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock:
        _conn.execute("CREATE TABLE IF NOT EXISTS settings "
                      "(k TEXT PRIMARY KEY, v TEXT)")
        _conn.execute("CREATE TABLE IF NOT EXISTS tasks "
                      "(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, "
                      "kind TEXT, status TEXT, detail TEXT, "
                      "created_at REAL, updated_at REAL)")
        _conn.commit()


def get_setting(key, default=""):
    with _lock:
        row = _conn.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
    return row["v"] if row else default


def set_setting(key, value):
    with _lock:
        _conn.execute("INSERT INTO settings(k, v) VALUES(?, ?) "
                      "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                      (key, value))
        _conn.commit()


def setting_updater(key):
    """返回一个回调：值非空且与库里不同才写回。

    给夸克客户端的 Cookie 轮换回写用（服务端 Set-Cookie 下发新值时持久化），
    其它驱动将来有同类续期需求也可复用。
    """
    def _update(value):
        if value and value != get_setting(key):
            set_setting(key, value)
    return _update


def create_task(title, kind):
    now = time.time()
    with _lock:
        cur = _conn.execute(
            "INSERT INTO tasks(title, kind, status, detail, created_at, updated_at) "
            "VALUES(?, ?, 'created', '{}', ?, ?)", (title, kind, now, now))
        _conn.commit()
        return cur.lastrowid


def update_task(task_id, status=None, detail=None):
    with _lock:
        if detail is not None:
            _conn.execute("UPDATE tasks SET detail=?, updated_at=? WHERE id=?",
                          (json.dumps(detail, ensure_ascii=False), time.time(), task_id))
        if status is not None:
            _conn.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                          (status, time.time(), task_id))
        _conn.commit()


def get_task(task_id):
    with _lock:
        row = _conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _row_to_task(row) if row else None


def list_tasks(limit=50):
    with _lock:
        rows = _conn.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT ?",
                             (limit,)).fetchall()
    return [_row_to_task(r) for r in rows]


def _row_to_task(row):
    return {
        "id": row["id"], "title": row["title"], "kind": row["kind"],
        "status": row["status"],
        "detail": json.loads(row["detail"] or "{}"),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }
