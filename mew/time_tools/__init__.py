"""
时间工具包
统一入口，合并原来分散的时间相关功能
"""

from time_tools.time_utils import (
    get_time,
    is_morning,
    is_night,
    is_sleep_time,
)
from time_tools.scheduler import (
    TimeTaskScheduler,
    scheduler,
    check_morning_night_greeting,
    check_silent_timeout,
    check_stay_timeout,
    TimeConfig,
)

__all__ = [
    "get_time",
    "is_morning",
    "is_night",
    "is_sleep_time",
    "TimeTaskScheduler",
    "scheduler",
    "check_morning_night_greeting",
    "check_silent_timeout",
    "check_stay_timeout",
    "TimeConfig",
]
