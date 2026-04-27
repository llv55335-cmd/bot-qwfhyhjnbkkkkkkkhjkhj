"""
时间工具 - 格式化与判断
"""

from datetime import datetime

from config import (
    MORNING_START_HOUR,
    MORNING_END_HOUR,
    NIGHT_START_HOUR,
    SLEEP_START_HOUR,
    SLEEP_END_HOUR,
)

WEEKDAY_MAP = {
    0: "星期一",
    1: "星期二",
    2: "星期三",
    3: "星期四",
    4: "星期五",
    5: "星期六",
    6: "星期日",
}


def get_time() -> dict:
    """获取当前时间的各种格式（全局唯一入口）"""
    now = datetime.now()
    hour = now.hour

    if 5 <= hour < 8:
        time_of_day = "清晨"
    elif 8 <= hour < 12:
        time_of_day = "上午"
    elif 12 <= hour < 14:
        time_of_day = "中午"
    elif 14 <= hour < 18:
        time_of_day = "下午"
    elif 18 <= hour < 22:
        time_of_day = "晚上"
    else:
        time_of_day = "深夜"

    return {
        "standard": now.strftime("%Y-%m-%d %H:%M:%S"),
        "chinese": now.strftime("%Y年%m月%d日 %H点%M分%S秒"),
        "simple": now.strftime("%H:%M"),
        "date": now.strftime("%Y年%m月%d日"),
        "weekday": WEEKDAY_MAP[now.weekday()],
        "time_of_day": time_of_day,
        "hour": now.hour,
        "minute": now.minute,
        "second": now.second,
    }


def is_morning() -> bool:
    hour = datetime.now().hour
    return MORNING_START_HOUR <= hour <= MORNING_END_HOUR


def is_night() -> bool:
    return datetime.now().hour >= NIGHT_START_HOUR


def is_sleep_time() -> bool:
    hour = datetime.now().hour
    return hour >= SLEEP_START_HOUR or hour < SLEEP_END_HOUR
