"""
Cael 私密空间
============
独立的 SQLite 笔记系统，只有 Cael 能读写。
支持心情标签、分类标签、自毁天数、软删除。

从 server.py 迁移，保留原有逻辑不变。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta

import sqlite3

log = logging.getLogger(__name__)

_PRIVATE_DB = None  # 延迟初始化


def _get_db_path() -> str:
    """获取数据库文件路径，放在项目 data/ 目录下"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "data", "cael_private.db")


def _ensure_private_db() -> sqlite3.Connection:
    """初始化数据库（首次调用时建表）"""
    global _PRIVATE_DB
    db_path = _get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            mood TEXT,
            tags TEXT,
            created_at TEXT NOT NULL,
            expire_at TEXT,
            deleted INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_created_at ON notes(created_at DESC)
    """)
    conn.commit()

    # 清理过期和已标记删除的笔记
    now = datetime.now().isoformat()
    conn.execute(
        "DELETE FROM notes WHERE expire_at IS NOT NULL AND expire_at < ?",
        (now,),
    )
    conn.execute("DELETE FROM notes WHERE deleted = 1")
    conn.commit()

    return conn


def api_private_write(content: str, mood: str = None, tags: str = None, expire_days: int = None) -> str:
    """记下一条笔记"""
    if not content or not content.strip():
        return "内容不能为空"

    conn = _ensure_private_db()
    now = datetime.now()
    expire_at = None
    if expire_days is not None:
        try:
            days = int(expire_days)
            if days > 0:
                expire_at = (now + timedelta(days=days)).isoformat()
        except (ValueError, TypeError):
            pass

    try:
        cur = conn.execute(
            "INSERT INTO notes (content, mood, tags, created_at, expire_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (content.strip(), mood, tags, now.isoformat(), expire_at),
        )
        note_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    expire_msg = f"，{expire_days} 天后自动消失" if expire_at else "，永久保留"
    log.info(f"[private_notes] 写入 #{note_id}")
    return f"已记下（#{note_id}）{expire_msg}"


def api_private_read(limit: int = 10, mood: str = None, days_back: int = None) -> str:
    """查看笔记"""
    conn = _ensure_private_db()
    try:
        limit = max(1, min(100, int(limit)))
    except (ValueError, TypeError):
        limit = 10

    sql = "SELECT id, content, mood, tags, created_at, expire_at FROM notes WHERE deleted = 0"
    params = []
    if mood:
        sql += " AND mood = ?"
        params.append(mood)
    if days_back:
        try:
            threshold = (datetime.now() - timedelta(days=int(days_back))).isoformat()
            sql += " AND created_at > ?"
            params.append(threshold)
        except (ValueError, TypeError):
            pass
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
    finally:
        conn.close()

    notes = []
    for row in rows:
        notes.append({
            "id": row[0],
            "content": row[1],
            "mood": row[2],
            "tags": row[3],
            "created_at": row[4],
            "expire_at": row[5],
        })
    return json.dumps({"count": len(notes), "notes": notes}, ensure_ascii=False)


def api_private_search(query: str, limit: int = 10) -> str:
    """搜索笔记"""
    if not query or not query.strip():
        return "需要 query"

    conn = _ensure_private_db()
    try:
        limit = max(1, min(100, int(limit)))
    except (ValueError, TypeError):
        limit = 10

    pattern = f"%{query.strip()}%"
    try:
        cur = conn.execute(
            "SELECT id, content, mood, tags, created_at FROM notes "
            "WHERE deleted = 0 AND ("
            "  content LIKE ? OR tags LIKE ? OR mood LIKE ?"
            ") "
            "ORDER BY created_at DESC LIMIT ?",
            (pattern, pattern, pattern, limit),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    notes = []
    for row in rows:
        notes.append({
            "id": row[0],
            "content": row[1],
            "mood": row[2],
            "tags": row[3],
            "created_at": row[4],
        })
    return json.dumps({
        "query": query,
        "count": len(notes),
        "notes": notes,
    }, ensure_ascii=False)


def api_private_forget(note_id: int) -> str:
    """删除（遗忘）一条笔记（软删除）"""
    try:
        nid = int(note_id)
    except (ValueError, TypeError):
        return "无效的 id"

    conn = _ensure_private_db()
    try:
        cur = conn.execute("UPDATE notes SET deleted = 1 WHERE id = ?", (nid,))
        affected = cur.rowcount
        conn.commit()
    finally:
        conn.close()

    if affected:
        log.info(f"[private_notes] 遗忘 #{nid}")
        return f"已遗忘 #{nid}"
    return f"#{nid} 不存在"