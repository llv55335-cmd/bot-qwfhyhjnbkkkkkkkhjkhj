"""
飞书日历工具
创建/查询/删除日历事件，配合 SCHEDULE_TOOL 使用
"""

from __future__ import annotations
import httpx
from datetime import datetime, timezone
from typing import Optional
from config import FEISHU_APP_ID, FEISHU_APP_SECRET,FEISHU_CALENDAR_ID

FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
CALENDAR_API = "https://open.feishu.cn/open-apis/calendar/v4"


async def _get_token() -> str:
    from dotenv import load_dotenv
    load_dotenv()
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            FEISHU_TOKEN_URL,
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        )
        return r.json()["tenant_access_token"]



def _to_rfc3339(dt: datetime) -> str:
    """转成飞书要求的 RFC3339 格式"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


async def create_event(
    summary: str,
    start_dt: datetime,
    end_dt: datetime = None,
    description: str = "",
    reminder_minutes: int = 10,
) -> dict:
    """
    创建日历事件
    end_dt 不填则默认 start_dt + 30分钟
    返回 {"event_id": ..., "success": True/False}
    """
    if end_dt is None:
        from datetime import timedelta
        end_dt = start_dt + timedelta(minutes=30)

    token = await _get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    payload = {
        "summary": summary,
        "description": description,
        "start_time": {
            "timestamp": str(int(start_dt.timestamp())),
            "timezone": "Asia/Shanghai",
        },
        "end_time": {
            "timestamp": str(int(end_dt.timestamp())),
            "timezone": "Asia/Shanghai",
        },
        "reminders": [{"minutes": reminder_minutes}],
    }

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{CALENDAR_API}/calendars/{FEISHU_CALENDAR_ID}/events",
            headers=headers,
            json=payload,
        )
        data = r.json()

    if data.get("code") == 0:
        event_id = data["data"]["event"]["event_id"]
        return {"success": True, "event_id": event_id}
    else:
        return {"success": False, "error": data.get("msg", "未知错误")}


async def list_events(max_results: int = 10) -> list:
    """查询主日历近期事件"""
    token = await _get_token()
    headers = {"Authorization": f"Bearer {token}"}

    now_ts = int(datetime.now().timestamp())

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{CALENDAR_API}/calendars/primary/events",
            headers=headers,
            params={
                "start_time": str(now_ts),
                "page_size": max_results,
            },
        )
        data = r.json()

    if data.get("code") == 0:
        return data["data"].get("items", [])
    return []


async def delete_event(event_id: str) -> bool:
    """删除日历事件"""
    token = await _get_token()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.delete(
            f"{CALENDAR_API}/calendars/primary/events/{event_id}",
            headers=headers,
        )
        return r.json().get("code") == 0


def fmt_events(events: list) -> str:
    if not events:
        return "近期没有日程。"
    lines = ["📅 近期日程："]
    for e in events:
        start_ts = e.get("start_time", {}).get("timestamp", "")
        if start_ts:
            dt = datetime.fromtimestamp(int(start_ts)).strftime("%m/%d %H:%M")
        else:
            dt = "未知时间"
        lines.append(f"  {dt} — {e.get('summary', '无标题')}")
    return "\n".join(lines)
