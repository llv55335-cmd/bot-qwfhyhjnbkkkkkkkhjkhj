"""
日程存储 - SQLite版
替换原来 memory/storage.py 里的日程部分
原来的 save_message / search_memories 保持不动，只替换日程相关函数
"""

import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from uuid import uuid4
from config import DATA_DIR

SCHEDULE_DB = os.path.join(DATA_DIR, "schedules.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(SCHEDULE_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                calendar_event_id TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                snoozed_until TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON schedules(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat ON schedules(chat_id)")


_init_db()


def save_schedule(
    chat_id: str,
    content: str,
    remind_at: datetime,
    calendar_event_id: str = None,
) -> Tuple[str, datetime]:
    schedule_id = str(uuid4())
    with _connect() as conn:
        conn.execute(
            """INSERT INTO schedules
               (id, chat_id, content, created_at, remind_at, status, calendar_event_id)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (
                schedule_id,
                chat_id,
                content,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                remind_at.strftime("%Y-%m-%d %H:%M:%S"),
                calendar_event_id,
            ),
        )
    return schedule_id, remind_at


def get_schedule(schedule_id: str) -> Optional[Dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM schedules WHERE id=?", (schedule_id,)
        ).fetchone()
        return dict(row) if row else None


def mark_schedule_done(schedule_id: str):
    with _connect() as conn:
        conn.execute(
            "UPDATE schedules SET status='done' WHERE id=?", (schedule_id,)
        )


def mark_schedule_cancelled(schedule_id: str):
    with _connect() as conn:
        conn.execute(
            "UPDATE schedules SET status='cancelled' WHERE id=?", (schedule_id,)
        )


def snooze_schedule(schedule_id: str, new_remind_at: datetime):
    """推迟提醒"""
    with _connect() as conn:
        conn.execute(
            """UPDATE schedules
               SET remind_at=?, status='pending', retry_count=retry_count+1
               WHERE id=?""",
            (new_remind_at.strftime("%Y-%m-%d %H:%M:%S"), schedule_id),
        )


def increment_retry(schedule_id: str):
    with _connect() as conn:
        conn.execute(
            "UPDATE schedules SET retry_count=retry_count+1 WHERE id=?",
            (schedule_id,),
        )


def list_schedules(chat_id: str, include_done: bool = False) -> List[Dict]:
    with _connect() as conn:
        if include_done:
            rows = conn.execute(
                "SELECT * FROM schedules WHERE chat_id=? ORDER BY remind_at",
                (chat_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM schedules WHERE chat_id=? AND status='pending' ORDER BY remind_at",
                (chat_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_all_pending() -> List[Dict]:
    """启动时恢复用：拿所有pending日程"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM schedules WHERE status='pending' ORDER BY remind_at"
        ).fetchall()
        return [dict(r) for r in rows]
