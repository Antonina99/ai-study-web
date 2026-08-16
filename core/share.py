# -*- coding: utf-8 -*-
"""
core/share.py —— 对外分享链接（SQLite 持久化）

功能：
- 生成唯一短码 token（secrets 随机，排除 0/O/1/l 等易混淆字符）；
- 记录分享目标（课程 course / 整个平台 app）、有效期（NULL=永久有效）；
- 查询 / 校验（含过期判断）/ 撤销 / 清理过期记录；
- 与 learning_tracker.db 共用同一数据库文件，新增 shares 表。

对外访问说明：
- 同一局域网：直接使用 `http://<本机IP>:8501/?share=<token>`；
- 公网访问：需把应用部署到公网服务器，或使用内网穿透 / 端口映射
  （如 ngrok / frp），再把「对外访问地址」改为对应的公网地址。
"""

import datetime
import secrets
import sqlite3

from core import tracker

# 排除易混淆字符（0/O、1/l/I），降低人工抄录出错概率
_TOKEN_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ"
_TOKEN_LEN = 10
_DT_FMT = "%Y-%m-%d %H:%M:%S"


def _conn():
    return sqlite3.connect(tracker.DB_PATH)


def _fmt(dt):
    return dt.strftime(_DT_FMT)


def _parse(s):
    """把存储的时间字符串解析为 datetime；空值返回 None。"""
    return datetime.datetime.strptime(s, _DT_FMT) if s else None


def init_db():
    """建表（幂等）。应用启动时调用一次。"""
    with _conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS shares ("
            " token TEXT PRIMARY KEY,"
            " target_type TEXT NOT NULL,"          # 'course' | 'app'
            " target_id TEXT,"                     # 课程索引 id（course 类型）
            " label TEXT,"                         # 展示名（课程名 / 整个平台）
            " career_direction TEXT,"              # 分享课程时的求职方向（思维导图主题）
            " created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),"
            " expires_at TEXT)"                    # NULL=永久有效
        )


def generate_token():
    """生成唯一短码（PRIMARY KEY 兜底去重）。"""
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_LEN))


def create_share(target_type, target_id=None, label="", career_direction=None, hours=None):
    """创建分享记录并返回完整记录。

    hours=None 表示永久有效；否则为有效小时数（到期后链接自动失效）。
    """
    token = generate_token()
    expires_at = None if hours is None else _fmt(
        datetime.datetime.now() + datetime.timedelta(hours=hours)
    )
    with _conn() as c:
        c.execute(
            "INSERT INTO shares (token, target_type, target_id, label, career_direction, expires_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (token, target_type, target_id, label or "", career_direction or "", expires_at),
        )
    return get_share(token)


def _row_to_dict(row):
    return {
        "token": row[0],
        "target_type": row[1],
        "target_id": row[2],
        "label": row[3],
        "career_direction": row[4],
        "created_at": row[5],
        "expires_at": row[6],
    }


def get_share(token):
    """按短码查询分享记录；不存在返回 None。"""
    if not token:
        return None
    with _conn() as c:
        row = c.execute("SELECT * FROM shares WHERE token = ?", (token,)).fetchone()
    return _row_to_dict(row) if row else None


def is_valid(rec):
    """永久有效（expires_at 为空）或尚未到过期时间。"""
    if not rec:
        return False
    expires = _parse(rec.get("expires_at"))
    return expires is None or expires > datetime.datetime.now()


def list_shares():
    """按创建时间倒序列出当前全部有效分享（已过期的不再展示）。"""
    with _conn() as c:
        rows = c.execute("SELECT * FROM shares ORDER BY created_at DESC, rowid DESC").fetchall()
    records = [_row_to_dict(r) for r in rows]
    return [r for r in records if is_valid(r)]


def delete_share(token):
    """撤销分享：删除记录后链接立即失效。"""
    if not token:
        return
    with _conn() as c:
        c.execute("DELETE FROM shares WHERE token = ?", (token,))


def purge_expired():
    """物理删除已过期的分享记录，避免长期堆积。"""
    with _conn() as c:
        c.execute(
            "DELETE FROM shares WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (_fmt(datetime.datetime.now()),),
        )


def get_default_base_url(port=8501):
    """自动探测本机局域网地址，作为分享链接的默认基础地址（可被用户覆盖）。"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # UDP connect 仅设置默认路由，不实际发包，离线也可用
            s.connect(("223.5.5.5", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and ip != "127.0.0.1":
            return f"http://{ip}:{port}"
    except Exception:
        pass
    return f"http://localhost:{port}"
