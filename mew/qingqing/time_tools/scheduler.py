"""
时间任务调度器 + 主动行为检查
"""

import asyncio
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from config import (
    SILENT_CHECK_HOURS,
    STAY_CHECK_SECONDS,
    MORNING_START_HOUR,
    MORNING_END_HOUR,
    NIGHT_START_HOUR,
    SLEEP_START_HOUR,
    SLEEP_END_HOUR,
    MIN_REMIND_DELAY_SECONDS,
)
from time_tools.time_utils import is_morning, is_night


class TimeConfig:
    """统一配置（从 config.py 读取，方便 feishu 等模块引用）"""

    MORNING_START = MORNING_START_HOUR
    MORNING_END = MORNING_END_HOUR
    NIGHT_START = NIGHT_START_HOUR
    SILENT_CHECK_HOURS = SILENT_CHECK_HOURS
    ENABLE_SILENT_AUTO_REPLY = True
    ENABLE_STAY_AUTO_REPLY = True
    STAY_CHECK_SECONDS = STAY_CHECK_SECONDS
    MIN_REMIND_DELAY_SECONDS = MIN_REMIND_DELAY_SECONDS
    SLEEP_START = SLEEP_START_HOUR
    SLEEP_END = SLEEP_END_HOUR


# ==================== 主动行为检查 ====================


async def check_morning_night_greeting() -> Tuple[Optional[str], Dict[str, Any], float]:
    from core.active_engine import universal_active_reply_engine

    if is_morning():
        situation = "早上"
    elif is_night():
        situation = "晚上"
    else:
        return None, {}, 0.0

    decision, usage, duration = await universal_active_reply_engine(situation)

    if decision and "SEND" in decision.upper():
        reply_content = decision.split("|")[-1].strip()
        return reply_content, usage, duration
    return None, {}, 0.0


async def check_silent_timeout(
    hours: float = None,
) -> Tuple[Optional[str], Dict[str, Any], float]:
    from core.active_engine import universal_active_reply_engine

    if not TimeConfig.ENABLE_SILENT_AUTO_REPLY:
        return None, {}, 0.0

    if hours is None:
        hours = TimeConfig.SILENT_CHECK_HOURS

    decision, usage, duration = await universal_active_reply_engine(
        f"已经 {hours} 小时没跟卿卿说话了"
    )

    if decision and "SEND" in decision.upper():
        reply_content = decision.split("|")[-1].strip()
        return reply_content, usage, duration
    return None, {}, 0.0


async def check_stay_timeout(
    seconds: int = None,
) -> Tuple[Optional[str], Dict[str, Any], float]:
    from core.active_engine import universal_active_reply_engine

    if not TimeConfig.ENABLE_STAY_AUTO_REPLY:
        return None, {}, 0.0

    if seconds is None:
        seconds = TimeConfig.STAY_CHECK_SECONDS

    decision, usage, duration = await universal_active_reply_engine(
        f"卿卿点开了对话框并盯着你看了{seconds}秒"
    )

    if decision and "SEND" in decision.upper():
        reply_content = decision.split("|")[-1].strip()
        return reply_content, usage, duration
    return None, {}, 0.0


# ==================== 调度器 ====================


class TimeTaskScheduler:
    def __init__(self):
        self.tasks = {}

    async def schedule_silent_check(
        self, chat_id: str, callback_func, hours: float = None
    ):
        if hours is None:
            hours = TimeConfig.SILENT_CHECK_HOURS

        task_key = f"silent_{chat_id}"
        if task_key in self.tasks:
            self.tasks[task_key].cancel()

        async def silent_task():
            try:
                await asyncio.sleep(hours * 3600)
                await callback_func(chat_id)
            except asyncio.CancelledError:
                pass

        self.tasks[task_key] = asyncio.create_task(silent_task())

    async def schedule_stay_check(
        self, chat_id: str, callback_func, seconds: int = None
    ):
        if seconds is None:
            seconds = TimeConfig.STAY_CHECK_SECONDS

        task_key = f"stay_{chat_id}"
        if task_key in self.tasks:
            self.tasks[task_key].cancel()

        async def stay_task():
            try:
                await asyncio.sleep(seconds)
                await callback_func(chat_id)
            except asyncio.CancelledError:
                pass

        self.tasks[task_key] = asyncio.create_task(stay_task())

    def cancel_all_tasks(self, chat_id: str):
        for task_key in list(self.tasks.keys()):
            if chat_id in task_key:
                self.tasks[task_key].cancel()
                del self.tasks[task_key]

    async def schedule_reminder(
        self,
        schedule_id: str,
        chat_id: str,
        remind_at: datetime,
        callback_func,
    ):
        task_key = f"reminder_{schedule_id}"
        if task_key in self.tasks:
            self.tasks[task_key].cancel()

        delay = max(
            (remind_at - datetime.now()).total_seconds(),
            TimeConfig.MIN_REMIND_DELAY_SECONDS,
        )

        async def reminder_task():
            try:
                await asyncio.sleep(delay)
                await callback_func(chat_id, schedule_id)
            except asyncio.CancelledError:
                pass

        self.tasks[task_key] = asyncio.create_task(reminder_task())


# 全局调度器实例
task_scheduler = TimeTaskScheduler()