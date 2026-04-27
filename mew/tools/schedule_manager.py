"""
日程管理器
负责：创建、提醒注入、状态流转（待确认→完成/推迟/取消/再提醒）
"""

from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional

from memory.storage_schedule import (
    save_schedule,
    get_schedule,
    mark_schedule_done,
    mark_schedule_cancelled,
    snooze_schedule,
    increment_retry,
    get_all_pending,
)
from tools.feishu_calendar import create_event, delete_event

# ==================== 待确认提醒暂存 ====================
pending_confirmations: Dict[str, dict] = {}

MAX_RETRY = 3
NO_RESPONSE_RETRY_SECONDS = 600

# 最近活跃时间 { chat_id: datetime }
last_active: Dict[str, datetime] = {}
ACTIVE_THRESHOLD_SECONDS = 120


def update_last_active(chat_id: str):
    """feishu.py 收到消息时调用"""
    last_active[chat_id] = datetime.now()


def is_in_conversation(chat_id: str) -> bool:
    last = last_active.get(chat_id)
    if not last:
        return False
    return (datetime.now() - last).total_seconds() < ACTIVE_THRESHOLD_SECONDS


# ==================== 创建日程 ====================

async def create_schedule(
    chat_id: str,
    content: str,
    remind_at: datetime,
    description: str = "",
) -> tuple[str, datetime]:
    """创建日程：写SQLite + 写飞书日历 + 挂asyncio task"""
    calendar_event_id = None
    try:
        cal_result = await create_event(content, remind_at, description=description)
        if cal_result.get("success"):
            calendar_event_id = cal_result.get("event_id")
            print(f"📅 飞书日历写入成功：{content} @ {remind_at}")
        else:
            print(f"⚠️ 飞书日历写入失败：{cal_result.get('error')}")
    except Exception as e:
        print(f"⚠️ 飞书日历异常：{e}")

    schedule_id, remind_dt = save_schedule(chat_id, content, remind_at, calendar_event_id)
    _schedule_task(schedule_id, chat_id, remind_at)
    return schedule_id, remind_dt


def restore_all_pending(chat_id_callback=None):
    """启动时恢复所有pending日程"""
    pending = get_all_pending()
    now = datetime.now()
    restored = 0
    for s in pending:
        try:
            remind_at = datetime.strptime(s["remind_at"], "%Y-%m-%d %H:%M:%S")
            if remind_at < now:
                remind_at = now + timedelta(seconds=5)
            _schedule_task(s["id"], s["chat_id"], remind_at)
            restored += 1
        except Exception as e:
            print(f"⚠️ 恢复日程失败 {s['id']}: {e}")
    print(f"📅 恢复了 {restored} 条日程")


# ==================== 内部task调度 ====================

_tasks: Dict[str, asyncio.Task] = {}


def _schedule_task(schedule_id: str, chat_id: str, remind_at: datetime):
    key = f"schedule_{schedule_id}"
    if key in _tasks and not _tasks[key].done():
        _tasks[key].cancel()

    delay = max(0, (remind_at - datetime.now()).total_seconds())

    async def _run():
        try:
            await asyncio.sleep(delay)
            await _fire_reminder(schedule_id, chat_id)
        except asyncio.CancelledError:
            pass

    _tasks[key] = asyncio.create_task(_run())


async def _fire_reminder(schedule_id: str, chat_id: str):
    """触发提醒：对话中注入，不在对话中主动发"""
    record = get_schedule(schedule_id)
    if not record or record["status"] != "pending":
        return

    content = record["content"]
    retry = record.get("retry_count", 0)

    if retry >= MAX_RETRY:
        mark_schedule_done(schedule_id)
        print(f"📅 日程 {schedule_id} 超过最大重试，自动完成")
        return

    pending_confirmations[chat_id] = {
        "schedule_id": schedule_id,
        "content": content,
        "injected_at": datetime.now(),
    }

    if is_in_conversation(chat_id):
        print(f"📅 对话中，提醒暂存等待注入：{content}")
    else:
        print(f"📅 非对话状态，主动发送提醒：{content}")
        await _send_active_reminder(chat_id, schedule_id, content)

    async def _no_response_retry():
        await asyncio.sleep(NO_RESPONSE_RETRY_SECONDS)
        if chat_id in pending_confirmations and \
                pending_confirmations[chat_id].get("schedule_id") == schedule_id:
            increment_retry(schedule_id)
            del pending_confirmations[chat_id]
            await _fire_reminder(schedule_id, chat_id)

    asyncio.create_task(_no_response_retry())


async def _send_active_reminder(chat_id: str, schedule_id: str, content: str):
    """主动调AI生成提醒语发到飞书"""
    try:
        from core.ai_core import call_ai, push_history
        from ports.feishu import send_to_feishu

        now = datetime.now().strftime("%H:%M")
        sid = schedule_id

        prompt = (
            f"[系统提醒：现在是{now}，用户设置的提醒「{content}」时间到了（ID:{sid}）。"
            f"请自然地提醒用户，不要自行判断已完成，等用户明确回应后在回复末尾另起一行输出："
            f"SCHEDULE_DONE|{sid} 或 SCHEDULE_DELAY|{sid}|时长 或 SCHEDULE_CANCEL|{sid}]"
        )

        reply, _, _ = await call_ai(prompt, chat_id=chat_id, caller="日程提醒")

        if reply:
            reply_lines = [l for l in reply.splitlines() if not l.strip().startswith("SCHEDULE_")]
            clean_reply = "\n".join(reply_lines).strip()
            await send_to_feishu(chat_id, clean_reply)
            push_history("assistant", clean_reply)

            for line in reply.splitlines():
                if line.strip().startswith("SCHEDULE_"):
                    await handle_schedule_directive(chat_id, line.strip())
                    break

    except Exception as e:
        print(f"❌ 主动提醒发送失败：{e}")


# ==================== 获取待注入的提醒文本 ====================

def get_pending_reminder_injection(chat_id: str) -> Optional[str]:
    conf = pending_confirmations.get(chat_id)
    if not conf:
        return None
    content = conf["content"]
    sid = conf["schedule_id"]
    now = datetime.now().strftime("%H:%M")
    return (
        f"[系统提醒：现在是{now}，提醒「{content}」时间到了（ID:{sid}）。"
        f"请自然地告知用户这个提醒，等用户明确说完成/推迟/取消后再输出对应指令，不要自行判断已完成。"
        f"用户确认后在回复末尾另起一行输出：SCHEDULE_DONE|{sid} 或 SCHEDULE_DELAY|{sid}|时长 或 SCHEDULE_CANCEL|{sid}]"
    )


# ==================== 处理AI返回的指令 ====================

async def handle_schedule_directive(chat_id: str, directive: str) -> Optional[str]:
    directive = directive.strip()
    if not directive.startswith("SCHEDULE_"):
        return None

    parts = [p.strip() for p in directive.split("|")]
    cmd = parts[0]
    schedule_id = parts[1] if len(parts) > 1 else ""

    if chat_id in pending_confirmations and \
            pending_confirmations[chat_id].get("schedule_id") == schedule_id:
        del pending_confirmations[chat_id]

    record = get_schedule(schedule_id)
    if not record:
        return None

    if cmd == "SCHEDULE_DONE":
        mark_schedule_done(schedule_id)
        if record.get("calendar_event_id"):
            await delete_event(record["calendar_event_id"])

    elif cmd == "SCHEDULE_DELAY":
        delay_str = parts[2] if len(parts) > 2 else "30m"
        new_dt = _parse_delay(delay_str)
        snooze_schedule(schedule_id, new_dt)
        _schedule_task(schedule_id, chat_id, new_dt)

    elif cmd == "SCHEDULE_CANCEL":
        mark_schedule_cancelled(schedule_id)
        if record.get("calendar_event_id"):
            await delete_event(record["calendar_event_id"])

    return None


def _parse_delay(s: str) -> datetime:
    now = datetime.now()
    s = s.strip().lower()
    try:
        if s.endswith("m"):
            return now + timedelta(minutes=int(s[:-1]))
        if s.endswith("h"):
            return now + timedelta(hours=int(s[:-1]))
        return datetime.strptime(s, "%Y-%m-%d %H:%M")
    except Exception:
        return now + timedelta(minutes=30)
