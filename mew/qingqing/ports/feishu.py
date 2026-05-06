"""
飞书消息端口
负责：收发消息、消息聚合、进入事件、命令路由、主动行为
"""

import os
import json
import asyncio
import httpx
import traceback
from datetime import datetime
from functools import wraps
from typing import Optional

import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from lark_oapi.ws import Client

from ports.base import SendResult
from core.ai_core import call_ai, push_history, conversation_history
from core.milestones import update_milestones
from core.token_commands import get_token_stats
from tools.schedule_manager import restore_all_pending, handle_schedule_directive, update_last_active
from time_tools import (
    scheduler,
    check_morning_night_greeting,
    check_silent_timeout,
    check_stay_timeout,
    is_sleep_time,
    TimeConfig,
)
import memory
from memory import schedule_service as schedule
from memory.storage_schedule import list_schedules
from config import (
    FEISHU_APP_ID,
    FEISHU_APP_SECRET,
    FEISHU_TENANT_TOKEN_URL,
    FEISHU_MESSAGE_URL,
    TOKEN_LOG_FILE,
    LAST_GREET_FILE,
)
from core.conversation_summarizer import on_message_round

# ==================== 飞书 API 工具 ====================


async def get_tenant_token() -> Optional[str]:
    url = FEISHU_TENANT_TOKEN_URL
    async with httpx.AsyncClient() as client:
        r = await client.post(
            url, json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
        )
        return r.json().get("tenant_access_token")


async def send_to_feishu(chat_id: str, content: str) -> bool:
    try:
        token = await get_tenant_token()
        if not token:
            print("[feishu] 获取飞书 token 失败")
            return False

        headers = {"Authorization": f"Bearer {token}"}
        msg_content = json.dumps({"text": content})
        payload = {"receive_id": chat_id, "msg_type": "text", "content": msg_content}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                FEISHU_MESSAGE_URL, headers=headers, json=payload
            )
            if response.status_code != 200:
                print(f"[feishu] 飞书发送失败: {response.text}")
                return False
            return True
    except Exception as e:
        print(f"[feishu] 发送消息到飞书出错: {e}")
        traceback.print_exc()
        return False


# ==================== 深夜保护装饰器 ====================


def sleep_protect(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        if is_sleep_time():
            print(f"[feishu] 深夜保护，拦截: {func.__name__}")
            return None
        return await func(*args, **kwargs)

    return wrapper


# ==================== Token 播报 ====================


async def send_token_monitor(chat_id, usage, duration, is_active=False):
    p_tk = usage.get("prompt_tokens", 0)
    c_tk = usage.get("completion_tokens", 0)
    total = p_tk + c_tk
    speed = round(c_tk / duration, 1) if duration > 0 else 0
    label = "主动撩人引擎" if is_active else "用户对话"
    msg = (
        f"🔹 模式：{label}\n"
        f"⏱️ 响应：{duration}s | 速度：{speed} tk/s\n"
        f"📤 上载：{p_tk} | 📥 下载：{c_tk} | 📊 总计：{total}"
    )
    await send_to_feishu(chat_id, msg)


# ==================== 消息聚合器 ====================


class MessageAggregator:
    def __init__(self, wait_seconds: int = 15):
        self.wait_seconds = wait_seconds
        self.buffer = {}
        self.tasks = {}

    def push(self, chat_id, text):
        if chat_id not in self.buffer:
            self.buffer[chat_id] = []
        self.buffer[chat_id].append(text)

        if chat_id in self.tasks and not self.tasks[chat_id].done():
            self.tasks[chat_id].cancel()

        self.tasks[chat_id] = asyncio.create_task(
            self._wait_and_reply(chat_id)
        )

    async def _wait_and_reply(self, chat_id):
        try:
            await asyncio.sleep(self.wait_seconds)
        except asyncio.CancelledError:
            return

        combined = "\n".join(self.buffer[chat_id])
        self.buffer[chat_id].clear()
        await process_and_reply(chat_id, combined)


aggregator = MessageAggregator(15)

# ==================== 状态 ====================

processed_ids = set()
entry_count = 0
active_wait_task = None
last_greet_date = ""


def _load_last_greet_date() -> str:
    global last_greet_date
    if os.path.exists(LAST_GREET_FILE):
        try:
            with open(LAST_GREET_FILE, "r", encoding="utf-8") as f:
                last_greet_date = f.read().strip()
        except Exception:
            last_greet_date = ""
    return last_greet_date


def _save_last_greet_date(date_str: str):
    global last_greet_date
    last_greet_date = date_str
    try:
        with open(LAST_GREET_FILE, "w", encoding="utf-8") as f:
            f.write(date_str)
    except Exception:
        pass


async def handle_schedule_directive_if_any(chat_id: str, directive: str):
    from tools.schedule_manager import handle_schedule_directive
    await handle_schedule_directive(chat_id, directive)


# ==================== 核心消息处理 ====================


async def process_and_reply(chat_id, text):
    """处理用户消息并回复"""
    print(f"[feishu] 思考用户消息: {text[:50]}...")
     
    update_last_active(chat_id)

    reply, usage, duration = await call_ai(text, chat_id=chat_id)

    if reply:
        # 检查 SCHEDULE 行
        # 解析日程指令
        for line in reply.splitlines():
            line = line.strip()
            if line.startswith("SCHEDULE_"):
                await handle_schedule_directive(chat_id, line)
                break

        # 清理回复里的指令行，不发给用户
        reply_lines = [l for l in reply.splitlines()
                    if not l.strip().startswith("SCHEDULE_")]
        reply = "\n".join(reply_lines).strip()

        # 发送回复
        ok = await send_to_feishu(chat_id, reply)

        # 记录历史
        push_history("user", text)
        push_history("assistant", reply)

        # 写入长期记忆
        memory.save_message(chat_id, "user", text)
        memory.save_message(chat_id, "assistant", reply)

        if ok:
            await send_token_monitor(chat_id, usage, duration, is_active=False)
        else:
            notice = "刚刚那条回复被系统拦住了，你可以换个说法再试一次～"
            await send_to_feishu(chat_id, notice)

        # 异步更新大事记
        asyncio.create_task(update_milestones(text, reply))

        # 接入对话总结器
        await on_message_round(chat_id, text, reply)
    else:
        fallback = "刚刚大脑开小差了，你可以稍后再问我一次～"
        await send_to_feishu(chat_id, fallback)


# ==================== 命令处理 ====================


async def handle_token_command(chat_id: str):
    try:
        msg = get_token_stats()
        await send_to_feishu(chat_id, msg)
    except Exception as e:
        await send_to_feishu(chat_id, f"[feishu] 获取 token 统计失败: {str(e)}")


# ==================== 主动行为 ====================


@sleep_protect
async def smart_silent_check(chat_id):
    try:
        reply_content, usage, duration = await check_silent_timeout()
        if reply_content:
            ok = await send_to_feishu(chat_id, reply_content)
            if ok:
                push_history("assistant", reply_content)
                await send_token_monitor(chat_id, usage, duration, is_active=True)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[feishu] 静默检查出错: {e}")


async def wait_and_ask_ai(chat_id):
    try:
        if not TimeConfig.ENABLE_STAY_AUTO_REPLY:
            return

        await asyncio.sleep(TimeConfig.STAY_CHECK_SECONDS)

        reply_content, usage, duration = await check_stay_timeout()
        if reply_content:
            ok = await send_to_feishu(chat_id, reply_content)
            if ok:
                push_history("assistant", reply_content)
                await send_token_monitor(chat_id, usage, duration, is_active=True)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[feishu] 停留检查出错: {e}")


async def check_morning_night(chat_id):
    global last_greet_date
    today = datetime.now().strftime("%Y-%m-%d")

    if not last_greet_date:
        _load_last_greet_date()

    if today == last_greet_date:
        return

    reply_content, usage, duration = await check_morning_night_greeting()

    if reply_content:
        _save_last_greet_date(today)
        ok = await send_to_feishu(chat_id, reply_content)
        if ok:
            push_history("assistant", reply_content)
            await send_token_monitor(chat_id, usage, duration, is_active=True)


# ==================== 飞书事件回调 ====================

_schedule_restored = False

def handle_message(data):
    """收到消息时的回调"""
    global entry_count, active_wait_task, _schedule_restored

    if not _schedule_restored:
        from tools.schedule_manager import restore_all_pending
        restore_all_pending(None)
        _schedule_restored = True

    msg_id = data.event.message.message_id
    if msg_id in processed_ids:
        return None
    processed_ids.add(msg_id)

    text_raw = data.event.message.content
    text = json.loads(text_raw).get("text", "")
    chat_id = data.event.message.chat_id

    # 命令路由
    # token 查询指令
    if text == "/token":
        asyncio.create_task(handle_token_command(chat_id))
        return None
    # 日程查询指令
    async def handle_schedules_command(chat_id: str):
        from memory.storage_schedule import list_schedules
        try:
            schedules = list_schedules(chat_id)
            if not schedules:
                await send_to_feishu(chat_id, "[feishu] 没有待提醒的日程～")
                return
            lines = ["📅 当前日程：", "================"]
            for idx, s in enumerate(schedules, start=1):
                lines.append(f"{idx}. {s.get('remind_at', '')[:16]}  ——  {s.get('content', '')}")
            await send_to_feishu(chat_id, "\n".join(lines))
        except Exception as e:
            await send_to_feishu(chat_id, f"[feishu] 获取日程失败: {str(e)}")

    # 重置计数和计时器
    entry_count = 0
    if active_wait_task:
        active_wait_task.cancel()

    scheduler.cancel_all_tasks(chat_id)
    aggregator.push(chat_id, text)
    asyncio.create_task(
        scheduler.schedule_silent_check(chat_id, smart_silent_check)
    )

    return None


def handle_enter_event(data):
    """用户进入聊天时的回调"""
    global entry_count, active_wait_task

    chat_id = data.event.chat_id
    entry_count += 1

    print(f"[feishu] 卿卿第 {entry_count} 次进入窗口")

    asyncio.create_task(check_morning_night(chat_id))

    if entry_count == 1:
        asyncio.create_task(
            scheduler.schedule_silent_check(chat_id, smart_silent_check)
        )

    if entry_count >= 2:
        if active_wait_task:
            active_wait_task.cancel()
        active_wait_task = asyncio.create_task(wait_and_ask_ai(chat_id))

    return None


# ==================== WS Client 构建（给 feishu_runner 调用） ====================


def build_ws_client():
    """构建并返回飞书 WS 客户端（不启动，由 feishu_runner 负责 start）"""
    event_handler = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(handle_message) \
        .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(handle_enter_event) \
        .build()

    client = Client(
        app_id=FEISHU_APP_ID,
        app_secret=FEISHU_APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    return client


# ==================== 定时任务 ====================


async def daily_check_weekly_review():
    """每天检查一次周总结和记忆维护"""
    while True:
        await asyncio.sleep(24 * 3600)
        try:
            from core.evolution import weekly_review
            from core.ai_core import conversation_history

            await weekly_review(conversation_history)
        except Exception as e:
            print(f"[feishu] 周总结检查出错: {e}")
        try:
            from memory.maintenance import run_weekly_maintenance_if_due

            await run_weekly_maintenance_if_due()
        except Exception as e:
            print(f"[feishu] 记忆维护检查出错: {e}")


print("[feishu] ports.feishu 已加载")