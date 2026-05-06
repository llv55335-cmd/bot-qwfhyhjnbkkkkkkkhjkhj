"""
日程管理服务
封装 storage 的日程能力 + scheduler 的提醒调度
"""

from __future__ import annotations

from datetime import datetime
from typing import Tuple, List, Dict, Any

import memory.storage as storage
from time_tools import scheduler


async def create_schedule(
    chat_id: str,
    content: str,
    remind_at: datetime,
    callback_func,
) -> Tuple[str, datetime]:
    schedule_id, remind_at_dt = storage.save_schedule(chat_id, content, remind_at)
    await scheduler.schedule_reminder(
        schedule_id, chat_id, remind_at_dt, callback_func
    )
    return schedule_id, remind_at_dt


def list_schedules(chat_id: str, include_done: bool = False) -> List[Dict[str, Any]]:
    return storage.list_schedules(chat_id, include_done=include_done)


def get_schedule(schedule_id: str) -> Dict | None:
    return storage.get_schedule(schedule_id)


def mark_schedule_done(schedule_id: str) -> None:
    storage.mark_schedule_done(schedule_id)
