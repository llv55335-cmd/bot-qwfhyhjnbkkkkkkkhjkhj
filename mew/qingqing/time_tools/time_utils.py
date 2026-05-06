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


# ===== 以下为 Task F 迁移的扩展工具 =====

from datetime import timezone, timedelta, date as dt_date
import time as _time_mod

TIMEZONE = timezone(timedelta(hours=8))


def now_iso():
    return datetime.now(TIMEZONE).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def today_str():
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d")


def this_week_monday_str():
    """本周一的日期字符串，周一为一周开始"""
    today = dt_date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime("%Y-%m-%d")


def this_month_str():
    return datetime.now(TIMEZONE).strftime("%Y-%m")


def parse_china_time(iso_str: str):
    """兼容 '2025-01-01T12:00:00+08:00' 和 '2025-01-01T12:00:00+0800' 等格式"""
    try:
        if iso_str.endswith("+08:00"):
            iso_str = iso_str[:-6] + "+0800"
        return datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return datetime.fromisoformat(iso_str)


def format_dt_cn(dt: datetime) -> str:
    return dt.astimezone(TIMEZONE).strftime("%Y年%m月%d日 %H:%M")


def is_today(iso_str: str) -> bool:
    try:
        t = parse_china_time(iso_str)
        return t.astimezone(TIMEZONE).date() == dt_date.today()
    except Exception:
        return False


def is_yesterday(iso_str: str) -> bool:
    try:
        t = parse_china_time(iso_str)
        return t.astimezone(TIMEZONE).date() == dt_date.today() - timedelta(days=1)
    except Exception:
        return False


def is_this_week(iso_str: str) -> bool:
    try:
        t = parse_china_time(iso_str)
        monday = dt_date.today() - timedelta(days=dt_date.today().weekday())
        return t.astimezone(TIMEZONE).date() >= monday
    except Exception:
        return False


def is_this_month(iso_str: str) -> bool:
    try:
        t = parse_china_time(iso_str)
        now = datetime.now(TIMEZONE)
        return t.year == now.year and t.month == now.month
    except Exception:
        return False


def days_ago(iso_str: str) -> int:
    try:
        t = parse_china_time(iso_str).astimezone(TIMEZONE).date()
        return (dt_date.today() - t).days
    except Exception:
        return -1


def format_relative_time(iso_str: str) -> str:
    try:
        t = parse_china_time(iso_str)
        now = datetime.now(TIMEZONE)
        diff = now - t
        seconds = diff.total_seconds()

        if seconds < 60:
            return "刚刚"
        elif seconds < 3600:
            return f"{int(seconds / 60)} 分钟前"
        elif seconds < 86400:
            return f"{int(seconds / 3600)} 小时前"
        elif seconds < 604800:
            return f"{int(seconds / 86400)} 天前"
        elif is_this_month(iso_str):
            return f"{int(seconds / 86400)} 天前"
        else:
            return format_dt_cn(t)
    except Exception:
        return iso_str