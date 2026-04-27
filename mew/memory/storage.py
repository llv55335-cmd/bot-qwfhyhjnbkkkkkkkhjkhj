"""
记忆与日程存储
当前实现用本地 JSON 文件，后面可以升级为 sqlite/向量搜索
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from uuid import uuid4

MEMORY_FILE = "memories.json"


def _load_all() -> List[Dict]:
    if not os.path.exists(MEMORY_FILE):
        return []
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_all(data: List[Dict]) -> None:
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ==================== 聊天记忆 ====================


def save_message(chat_id: str, role: str, content: str) -> None:
    data = _load_all()
    data.append(
        {
            "id": str(uuid4()),
            "type": "chat",
            "chat_id": chat_id,
            "role": role,
            "content": content,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    _save_all(data)


def search_memories(chat_id: str, keyword: str, limit: int = 5) -> List[Dict]:
    data = _load_all()
    result = [
        item
        for item in data
        if item.get("type") == "chat"
        and item.get("chat_id") == chat_id
        and keyword in item.get("content", "")
    ]
    return result[-limit:]


# ==================== 日程提醒 ====================


def save_schedule(
    chat_id: str, content: str, remind_at: datetime
) -> Tuple[str, datetime]:
    data = _load_all()
    schedule_id = str(uuid4())
    record = {
        "id": schedule_id,
        "type": "schedule",
        "chat_id": chat_id,
        "content": content,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "remind_at": remind_at.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "pending",
    }
    data.append(record)
    _save_all(data)
    return schedule_id, remind_at


def get_schedule(schedule_id: str) -> Optional[Dict]:
    data = _load_all()
    for item in data:
        if item.get("id") == schedule_id and item.get("type") == "schedule":
            return item
    return None


def mark_schedule_done(schedule_id: str) -> None:
    data = _load_all()
    changed = False
    for item in data:
        if item.get("id") == schedule_id and item.get("type") == "schedule":
            item["status"] = "done"
            changed = True
            break
    if changed:
        _save_all(data)


def list_schedules(chat_id: str, include_done: bool = False):
    data = _load_all()
    schedules = [
        item
        for item in data
        if item.get("type") == "schedule"
        and item.get("chat_id") == chat_id
        and (include_done or item.get("status") != "done")
    ]
    schedules.sort(key=lambda x: x.get("remind_at", ""))
    return schedules
