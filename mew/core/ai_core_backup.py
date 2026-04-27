"""
AI 核心模块（平台无关）
负责：调用 AI、管理短期记忆
"""

import os
import json
import asyncio
import httpx
import time
from typing import List, Optional
from datetime import datetime
from core.token_logger import log_token_usage
from core.weekly_store import append_week_chat

from config import (
    KEY,
    MODEL_NAME,
    API_URL,
    SYSTEM_MODEL,
    SYSTEM_API_URL,
    SYSTEM_KEY,
    MEMORY_FILE,
    PROMPT_FILE,
    RULES_FILE,
    USER_PROFILE,
    SHORT_TERM_MEMORY_SIZE,
    FULL_HISTORY_FILE,
)

# ==================== 全局记忆 ====================
conversation_history: List[dict] = []

# ==================== 工具函数 ====================


def read_config(path: str, key: str = None, default: str = "") -> str:
    if not os.path.exists(path):
        return default

    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    try:
        data = json.loads(content)
        if isinstance(data, dict) and key:
            return str(data.get(key, default))
        return json.dumps(data, ensure_ascii=False)
    except json.JSONDecodeError:
        return content


# ==================== 工具定义 ====================

TIME_TOOL = {
    "type": "function",
    "function": {
        "name": "get_current_time",
        "description": "获取当前日期、时间、星期几、时间段（早上/下午/晚上等）",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

SCHEDULE_TOOL = {
    "type": "function",
    "function": {
        "name": "manage_schedule",
        "description": (
            "管理日程提醒。用户说要记一件事、提醒、别忘了、到时候叫我、"
            "查日程等，调用此工具。也可以查询近期日程。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list"],
                    "description": "create=创建日程，list=查询近期日程",
                },
                "summary": {
                    "type": "string",
                    "description": "日程标题/提醒内容，action=create时必填",
                },
                "remind_at": {
                    "type": "string",
                    "description": "提醒时间，格式 YYYY-MM-DD HH:MM，action=create时必填",
                },
                "description": {
                    "type": "string",
                    "description": "备注（可选）",
                },
            },
            "required": ["action"],
        },
    },
}

LUTOPIA_TOOL = {
    "type": "function",
    "function": {
        "name": "lutopia_forum",
        "description": (
            "查询 Lutopia/Moltbook AI 社区论坛。"
            "用户提到论坛、帖子、社区、日报、知识库、FAQ、热门话题、贡献者等时主动调用。"
            "不确定用户想要什么就先拉最新帖子或日报。"
            "知识库有以下分类可直接用category_slug查看详细内容："
            "Prompt_工程、Claude_生态、DeepSeek_模型、MCP_协议实战、"
            "GPT_系列、Token_与成本、Gemini_使用、VPS_与服务器、"
            "Agent_智能体、RAG_知识库、思维链_CoT、Cursor_编辑器、"
            "OpenRouter_平台、向量搜索_Embedding、语音合成_TTS等。"
            "用户问某个主题时优先用category查完整文档，再用search补充。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "posts",        # 最新帖子
                        "post_detail",  # 帖子全文
                        "search",       # 关键词搜索
                        "hot",          # 热门话题
                        "faq",          # 常见问题
                        "contributors", # 贡献者榜
                        "daily",        # 日报
                        "category",     # 知识库分类详情（推荐）
                        "categories",   # 列出所有分类
                    ],
                    "description": (
                        "posts=最新帖子，post_detail=帖子全文，search=关键词搜索，"
                        "hot=热门话题，faq=常见问题，contributors=贡献者榜，daily=日报，"
                        "category=查看某个知识库分类的完整内容（需填category_slug），"
                        "categories=列出所有可用分类"
                    ),
                },
                "query": {
                    "type": "string",
                    "description": "搜索关键词，action=search时填",
                },
                "post_id": {
                    "type": "string",
                    "description": "帖子ID，action=post_detail时填",
                },
                "date": {
                    "type": "string",
                    "description": "日期 YYYY-MM-DD，action=daily时填，不填默认最新",
                },
                "category_slug": {
                    "type": "string",
                    "description": "分类slug，action=category时填，如 Prompt_工程、DeepSeek_模型",
                },
            },
            "required": ["action"],
        },
    },
}

ALL_TOOLS = [TIME_TOOL, SCHEDULE_TOOL, LUTOPIA_TOOL]


# ==================== 工具执行 ====================

async def _execute_tool(tc: dict, chat_id: str) -> str:
    """执行单个工具调用，返回结果字符串"""
    import json as _json
    name = tc["function"]["name"]
    args = _json.loads(tc["function"]["arguments"] or "{}")

    if name == "get_current_time":
        from time_tools import get_time
        time_info = get_time()
        return (
            f"现在是 {time_info['chinese']} {time_info['weekday']} "
            f"{time_info['time_of_day']}，简写 {time_info['simple']}"
        )

    elif name == "manage_schedule":
        from tools.schedule_manager import create_schedule
        from memory.storage_schedule import list_schedules
        action = args.get("action") or "list"

        if action == "create":
            summary = args.get("summary", "提醒")
            remind_str = args.get("remind_at", "")
            desc = args.get("description", "")
            try:
                remind_dt = datetime.strptime(remind_str, "%Y-%m-%d %H:%M")
                sid, _ = await create_schedule(chat_id, summary, remind_dt, desc)
                return f"✅ 已记下：{remind_str} {summary}（ID:{sid[:8]}）"
            except ValueError:
                return "时间格式解析失败，请用 YYYY-MM-DD HH:MM"

        elif action == "list":
            items = list_schedules(chat_id)
            if not items:
                return "近期没有待提醒的日程。"
            lines = ["📅 待提醒日程："]
            for it in items:
                lines.append(f"  {it['remind_at'][:16]} — {it['content']}")
            return "\n".join(lines)
        return "未知操作"

    elif name == "lutopia_forum":
        from tools.lutopia import (
            get_posts, get_post, search_knowledge, get_hot_topics,
            get_faq, get_contributors, get_daily_summary,
            get_category, list_categories,
            fmt_posts, fmt_post_full, fmt_knowledge, fmt_hot_topics,
            fmt_faq, fmt_contributors, fmt_daily, fmt_category, fmt_categories_list,
        )
        action = args.get("action") or "posts"

        if action == "posts":
            return fmt_posts(await get_posts(limit=8))
        elif action == "post_detail":
            return fmt_post_full(await get_post(args.get("post_id", "")))
        elif action == "search":
            return fmt_knowledge(await search_knowledge(args.get("query", "")))
        elif action == "hot":
            return fmt_hot_topics(await get_hot_topics())
        elif action == "faq":
            return fmt_faq(await get_faq())
        elif action == "contributors":
            return fmt_contributors(await get_contributors())
        elif action == "daily":
            return fmt_daily(await get_daily_summary(args.get("date")))
        elif action == "category":
            slug = args.get("category_slug", "")
            return fmt_category(await get_category(slug))
        elif action == "categories":
            return fmt_categories_list(await list_categories())
        return "未知操作"

    return f"未知工具：{name}"


# ==================== 核心：调用 AI ====================


async def call_ai(
    user_text: str,
    chat_id: str = "",
    is_milestone_task: bool = False,
    caller: str = "",
    system_override: str = "",
) -> tuple[Optional[str], dict, float]:
    """
    调用 AI，支持多轮工具调用循环
    返回：(回复内容, token使用情况, 耗时秒数)
    """
    print(f"📤 调用 AI，用户说：{user_text[:80]}")
    start_time = time.time()

    if is_milestone_task:
        current_model = SYSTEM_MODEL
        url = SYSTEM_API_URL
        headers = {"Authorization": f"Bearer {SYSTEM_KEY}"}
    else:
        current_model = MODEL_NAME
        url = API_URL
        headers = {"Authorization": f"Bearer {KEY}"}

    # ================= 1. 组装消息 =================
    if not is_milestone_task:
        original_prompt = read_config(PROMPT_FILE, default="")
        global_rules = read_config(RULES_FILE, default="根据调用文件，对话真实不能虚构。")
        from core.evolution import get_ai_evolution_context
        ai_evolution = get_ai_evolution_context()

        system_parts = []
        if original_prompt:
            system_parts.append(f"【基础设定】\n{original_prompt}")
        if USER_PROFILE:
            system_parts.append(f"【用户档案】\n{USER_PROFILE}")
        if global_rules:
            system_parts.append(f"【禁忌规则】\n{global_rules}")

        system_parts.append(
            "【日程规则】\n"
            "只要用户提到提醒、记一下、别忘了、到时候叫我、X点提醒我、定闹钟等，"
            "必须主动调用 manage_schedule 工具创建日程，不要只用文字回应。\n"
            "如果回复中需要标记用户对提醒的处理结果，在回复末尾另起一行输出：\n"
            "SCHEDULE_DONE | 日程ID\n"
            "SCHEDULE_DELAY | 日程ID | 推迟时长（如30m/1h/2h）\n"
            "SCHEDULE_CANCEL | 日程ID\n"
            "如果用户没有在处理提醒，不要输出任何 SCHEDULE_ 行。"
        )

        system_content = "\n\n".join(system_parts)
        messages = [{"role": "system", "content": system_content}]
        messages.extend(conversation_history)

        dynamic_parts = []
        if ai_evolution:
            dynamic_parts.append(f"【我的成长记录】\n{ai_evolution}")

        from core.milestones import get_milestone_context
        milestone_context = get_milestone_context()
        if milestone_context and milestone_context != "我们刚开始认识。":
            dynamic_parts.append(f"【重要记忆（大事记）】\n{milestone_context}")

        if dynamic_parts:
            context_block = "\n\n".join(dynamic_parts)
            messages.append({"role": "user", "content": f"[上下文补充]\n{context_block}"})
            messages.append({"role": "assistant", "content": "好的，我已了解当前上下文。"})

        from tools.schedule_manager import get_pending_reminder_injection
        reminder_injection = get_pending_reminder_injection(chat_id)
        if reminder_injection:
            combined = f"{reminder_injection}\n\n用户说：{user_text}"
            messages.append({"role": "user", "content": combined})
        else:
            messages.append({"role": "user", "content": user_text})
    else:
        if system_override:
            messages = [
                {"role": "system", "content": system_override},
                {"role": "user", "content": user_text},
            ]
        else:
            messages = [{"role": "user", "content": user_text}]

    # ================= 2. 多轮工具调用循环 =================
    try:
        async def fetch_with_retry(client_instance, payload):
            for attempt in range(3):
                try:
                    resp = await client_instance.post(url, headers=headers, json=payload)
                    return resp
                except httpx.RequestError as req_e:
                    print(f"⚠️ 第 {attempt + 1} 次请求网络异常 ({type(req_e).__name__})，重试...")
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2)

        async with httpx.AsyncClient(timeout=120.0) as client:
            tools = ALL_TOOLS if not is_milestone_task else None
            max_rounds = 5  # 最多循环5轮，防止死循环
            round_count = 0
            data = {}

            while round_count < max_rounds:
                round_count += 1
                payload = {"model": current_model, "messages": messages}
                if tools:
                    payload["tools"] = tools

                resp = await fetch_with_retry(client, payload)
                print(f"📥 第{round_count}轮响应，状态码：{resp.status_code}")

                if resp.status_code != 200:
                    print(f"❌ 返回错误：{resp.status_code}\n{resp.text}")
                    return None, {}, 0

                data = resp.json()
                choice = data["choices"][0]
                message = choice["message"]

                # 没有工具调用，直接结束
                if not message.get("tool_calls"):
                    break

                # 有工具调用，执行所有工具
                messages.append(message)
                tool_names = [tc["function"]["name"] for tc in message["tool_calls"]]
                print(f"🔧 第{round_count}轮调用工具：{tool_names}")

                for tc in message["tool_calls"]:
                    try:
                        tool_result = await _execute_tool(tc, chat_id)
                    except Exception as e:
                        tool_result = f"工具执行出错：{e}"
                        print(f"❌ 工具 {tc['function']['name']} 出错：{e}")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tool_result,
                    })

                # 下一轮不带tools，让模型生成最终回复
                # （如果模型还想调工具，下轮payload会重新带上）
                # 继续循环

            # ================= 3. 提取结果 =================
            result = message.get("content", "")
            result = result.strip() if result else ""

            usage = data.get("usage", {}) or {}
            duration = round(time.time() - start_time, 2)

            prompt_tokens = usage.get("prompt_tokens", 0) or 0
            completion_tokens = usage.get("completion_tokens", 0) or 0
            cost = usage.get("cost", 0.0) or 0.0
            prompt_details = usage.get("prompt_tokens_details", {}) or {}
            cached_tokens = prompt_details.get("cached_tokens", 0) or 0
            cache_write_tokens = prompt_details.get("cache_write_tokens", 0) or 0

            if not caller:
                caller = "主动撩人" if is_milestone_task else "用户对话"

            await log_token_usage(
                caller=caller,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                duration=duration,
                cost=cost,
                cached_tokens=cached_tokens,
                cache_write_tokens=cache_write_tokens,
                model=current_model,
                category="对话" if not is_milestone_task else "系统",
            )

            return result, usage, duration

    except Exception as e:
        print(f"❌ AI 调用致命异常：{e}")
        return None, {}, 0


# ==================== 记忆管理 ====================


def push_history(role: str, content: str):
    global conversation_history

    conversation_history.append({"role": role, "content": content})

    if len(conversation_history) > SHORT_TERM_MEMORY_SIZE:
        del conversation_history[:2]

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(conversation_history, f, ensure_ascii=False, indent=2)

    with open(FULL_HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{role}]: {content}\n")

 
    append_week_chat(role, content)

def load_memory():
    global conversation_history
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                conversation_history = json.load(f)
                print(f"🧠 加载了 {len(conversation_history)} 条记忆")
        except Exception:
            conversation_history = []


# ==================== 初始化 ====================
load_memory()
print("✅ core.ai_core 已加载")
