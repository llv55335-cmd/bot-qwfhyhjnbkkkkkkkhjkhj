"""
数据库迁移脚本
在现有 graph_memory.db 上补字段 + 建新表
安全：只 ADD，不删不改已有数据
运行：python migrate_db.py
"""

import os
import sqlite3

DATA_DIR = os.getenv("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(DATA_DIR, "graph_memory.db")


def migrate(db_path: str = DB_PATH):
    print(f"📂 数据库路径：{db_path}")
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON;")

    # ── 1. memories 表补字段（旧库升级用；新库由 graph_store 建表，跳过）──
    tables = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "memories" in tables:
        existing = {
            row[1]
            for row in conn.execute("PRAGMA table_info(memories)").fetchall()
        }
        new_cols = {
            "decay_score":  "REAL NOT NULL DEFAULT 1.0",
            "access_count": "INTEGER NOT NULL DEFAULT 0",
            "status":       "TEXT NOT NULL DEFAULT 'active'",
            "embedding_id": "INTEGER",
        }
        for col, definition in new_cols.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE memories ADD COLUMN {col} {definition}")
                print(f"  ✅ memories.{col} 已添加")
            else:
                print(f"  ⏭  memories.{col} 已存在，跳过")
    else:
        print("  ⏭  memories 表不存在（新库），跳过字段迁移，由 GraphStore 建表")

    # ── 2. snapshots 表 ───────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id   INTEGER NOT NULL,
            content_snap TEXT NOT NULL,
            paths_snap  TEXT NOT NULL,
            snapped_at  TEXT NOT NULL,
            confirmed_by TEXT NOT NULL DEFAULT '{"ai":false,"user":false}',
            reason      TEXT,
            FOREIGN KEY (memory_id) REFERENCES memories(id)
        )
    """)
    print("  ✅ snapshots 表就绪")

    # ── 3. co_occurrence 表 ───────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS co_occurrence (
            memory_id_a INTEGER NOT NULL,
            memory_id_b INTEGER NOT NULL,
            count       INTEGER NOT NULL DEFAULT 1,
            last_seen   TEXT NOT NULL,
            PRIMARY KEY (memory_id_a, memory_id_b),
            FOREIGN KEY (memory_id_a) REFERENCES memories(id),
            FOREIGN KEY (memory_id_b) REFERENCES memories(id)
        )
    """)
    print("  ✅ co_occurrence 表就绪")

    # ── 4. pending_confirmations 表（双确认队列）─────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_confirmations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            op_type     TEXT NOT NULL,   -- 'add' / 'edit' / 'delete'
            memory_id   INTEGER,
            payload     TEXT NOT NULL,   -- JSON
            ai_ok       INTEGER NOT NULL DEFAULT 0,
            user_ok     INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        )
    """)
    print("  ✅ pending_confirmations 表就绪")

    # ── 5. 索引（仅在表存在时建）──────────────────────────
    tables_now = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "memories" in tables_now:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_decay ON memories(decay_score)"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_co_occ_a ON co_occurrence(memory_id_a)"
    )

    conn.commit()
    conn.close()
    print("\n🎉 迁移完成")


if __name__ == "__main__":
    migrate()
