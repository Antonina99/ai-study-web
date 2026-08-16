# -*- coding: utf-8 -*-
"""
core/tracker.py —— 本地轻量持久化（SQLite）

作用：将错题本与学习统计从「仅内存」提升为「落盘」，刷新页面后学习进度不丢失。
- 错题本 wrongs：全量覆盖式保存（每次提交后重写）。
- 学习统计 stats：单行 upsert。
数据文件：项目根目录 learning_tracker.db
"""

import json
import os
import sqlite3

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_PROJECT_ROOT, "learning_tracker.db")


def _conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    """建表并保证 stats 存在首行。应用启动时调用一次。"""
    with _conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS stats ("
            " id INTEGER PRIMARY KEY CHECK (id = 1),"
            " answered INTEGER NOT NULL DEFAULT 0,"
            " correct INTEGER NOT NULL DEFAULT 0)"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS wrongs ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " q TEXT, options TEXT, answer INTEGER, explain TEXT,"
            " source TEXT, user_ans INTEGER,"
            " created_at TEXT DEFAULT (datetime('now','localtime')))"
        )
        c.execute("INSERT OR IGNORE INTO stats (id, answered, correct) VALUES (1, 0, 0)")


# ---------------------------------------------------------------- stats
def load_stats():
    with _conn() as c:
        row = c.execute("SELECT answered, correct FROM stats WHERE id = 1").fetchone()
    return {"answered": int(row[0]), "correct": int(row[1])} if row else {"answered": 0, "correct": 0}


def save_stats(stats):
    with _conn() as c:
        c.execute(
            "UPDATE stats SET answered = ?, correct = ? WHERE id = 1",
            (int(stats.get("answered", 0)), int(stats.get("correct", 0))),
        )


# ---------------------------------------------------------------- wrongs
def load_wrongs():
    """从 SQLite 还原错题本（内存中的 dict 结构）。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT q, options, answer, explain, source, user_ans FROM wrongs ORDER BY id"
        ).fetchall()
    wrongs = []
    for q, options, answer, explain, source, user_ans in rows:
        try:
            opts = json.loads(options) if options else []
        except (json.JSONDecodeError, TypeError):
            opts = []
        wrongs.append({
            "q": q or "",
            "options": opts,
            "answer": answer,
            "explain": explain or "",
            "source": source or "",
            "user_ans": user_ans,
        })
    return wrongs


def save_wrongs(wrongs):
    """全量覆盖写入错题本（保持内存顺序）。"""
    with _conn() as c:
        c.execute("DELETE FROM wrongs")
        for w in wrongs:
            c.execute(
                "INSERT INTO wrongs (q, options, answer, explain, source, user_ans)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    w.get("q", ""),
                    json.dumps(w.get("options", []), ensure_ascii=False),
                    w.get("answer", 0),
                    w.get("explain", ""),
                    w.get("source", ""),
                    w.get("user_ans"),
                ),
            )
