"""生命周期维护 - 保留现状"""
from __future__ import annotations
import json, os, sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from config import DATA_DIR
from .openrouter_client import chat_json
from .graph_store import GraphStore

LAST_MAINT_FILE = os.path.join(DATA_DIR, "memory_last_maintenance.txt")

def _read_last():
    if not os.path.exists(LAST_MAINT_FILE): return None
    try:
        dt = datetime.fromisoformat(open(LAST_MAINT_FILE).read().strip())
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except: return None

def _write_last(dt):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LAST_MAINT_FILE, "w") as f: f.write(dt.isoformat())

async def run_weekly_maintenance_if_due(force=False):
    last = _read_last()
    now = datetime.now(timezone.utc)
    if not force and last and now - last < timedelta(days=7): return None
    store = GraphStore()
    with sqlite3.connect(store.db_path, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        aliases = [dict(r) for r in conn.execute(
            "SELECT p.domain,p.path,e.disclosure,m.id AS memory_id,m.summary,m.content,m.importance,m.is_permanent,m.created_at,m.usage_count "
            "FROM paths p JOIN edges e ON e.id=p.edge_id JOIN memories m ON m.node_uuid=e.child_uuid WHERE m.deprecated=0 ORDER BY m.importance DESC LIMIT 50"
        ).fetchall()]
    if not aliases:
        _write_last(now); return None
    try:
        report = await chat_json(
            "你是记忆维护助手。输出严格JSON。",
            f"活动记忆：{json.dumps(aliases[:30], ensure_ascii=False)}\n给出清理/合并建议，JSON格式。"
        )
    except Exception as e:
        report = {"error": str(e)}
    path = os.path.join(DATA_DIR, f"memory_maintenance_{now.strftime('%Y%m%d_%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f: json.dump(report, f, ensure_ascii=False, indent=2)
    _write_last(now)
    return path
