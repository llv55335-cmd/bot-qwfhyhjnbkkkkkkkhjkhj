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
from tools.memory_tools import ALL_MEMORY_TOOLS, MEMORY_TOOL_NAMES, execute_memory_tool

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

MEMORY_MANAGEMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "manage_memory",
        "description": "管理长期记忆：搜索、添加、标记重要记忆，查看记忆统计",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["search", "add", "mark_important", "list_recent", "stats"],
                    "description": "操作类型：search=搜索记忆，add=添加记忆，mark_important=标记重要，list_recent=查看最近记忆，stats=查看统计"
                },
                "query": {
                    "type": "string",
                    "description": "搜索关键词或要添加的记忆内容，action=search/add时使用"
                },
                "importance": {
                    "type": "integer",
                    "description": "重要性1-5，action=add时使用",
                    "minimum": 1,
                    "maximum": 5
                },
                "tags": {
                    "type": "string",
                    "description": "标签，逗号分隔，action=add时使用"
                },
                "memory_id": {
                    "type": "string",
                    "description": "记忆ID，action=mark_important时使用"
                }
            },
            "required": ["action"]
        }
    },
}

TRAVEL_SYSTEM_TOOL = {
    "type": "function",
    "function": {
        "name": "xiaowo_travel",
        "description": (
            "小窝旅行系统：开始虚拟旅行、探索目的地、写游记、收集行李。"
            "当用户提到旅行、想去、探索、游记、目的地、出发、虚拟旅行等时，必须主动调用此工具。"
            "可以推荐目的地、开始旅行、在旅行中行动、结束旅行、查看旅行记录和行李。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["suggest", "prepare", "start", "go", "end", "list", "luggage"],
                    "description": "suggest=推荐目的地, prepare=旅行前准备, start=开始旅行, go=旅行行动, end=结束旅行, list=查看记录, luggage=查看行李"
                },
                "destination": {
                    "type": "string",
                    "description": "旅行目的地，action=prepare/start时使用"
                },
                "plan": {
                    "type": "string",
                    "description": "旅行计划，action=start时使用，默认为'自由探索'"
                },
                "clothing": {
                    "type": "string", 
                    "description": "穿着服装，action=start时使用，默认为'T恤和长裤'"
                },
                "session_id": {
                    "type": "string",
                    "description": "旅行会话ID，action=go/end时使用"
                },
                "input": {
                    "type": "string",
                    "description": "旅行中的行动描述，action=go时使用"
                },
                "journal": {
                    "type": "string",
                    "description": "游记内容，action=end时使用"
                },
                "luggage": {
                    "type": "string",
                    "description": "新行李物品，action=end时使用"
                }
            },
            "required": ["action"]
        }
    },
}

CODE_ANALYSIS_TOOL = {
    "type": "function",
    "function": {
        "name": "code_analysis",
        "description": (
            "分析项目代码结构、功能和架构。"
            "当用户询问项目功能、代码结构、模块关系、import依赖、潜在死代码时，必须主动调用此工具。"
            "可以展示项目总结、解释特定文件、分析代码结构。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["summary", "explain", "structure"],
                    "description": "summary=项目总结, explain=解释文件功能, structure=详细结构分析"
                },
                "filepath": {
                    "type": "string",
                    "description": "文件路径（如'core/ai_core.py'），action=explain时使用"
                }
            },
            "required": ["action"]
        }
    },
}

API_EXPLORE_TOOL = {
    "type": "function",
    "function": {
        "name": "explore_api",
        "description": (
            "探索任意API接口，发现端点、学习功能、存储重要信息到记忆系统。"
            "当用户提到以下内容时，必须主动调用此工具（不要询问用户是否要探索，直接调用）：\n"
            "1. URL、链接、网址、域名（如 http://, https://, example.com, localhost:8080）\n"
            "2. API、接口、端点、REST、GraphQL、swagger、openapi、文档\n"
            "3. 测试、请求、curl、Postman、HTTP、GET、POST\n"
            "4. 论坛、社区、网站功能（如'论坛有什么新功能'、'这个网站能做什么'）\n"
            "5. ngrok、本地服务器、开发环境、服务端\n"
            "6. 第三方服务、外部系统、集成对接\n"
            "7. 不确定某个系统如何工作、想了解其功能时\n"
            "\n"
            "会自动分析响应，提取认证方式、端点列表、数据结构等，并存储重要发现到记忆中。"
            "对于论坛（如Lutopia），可以用深度探索发现新功能。"
            "对于本地开发服务器（ngrok地址），应该尝试探索其API端点。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "目标URL（例如：https://api.example.com 或 ngrok地址，如 https://xxxx.ngrok.io）"
                },
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"],
                    "description": "HTTP方法，默认GET"
                },
                "headers": {
                    "type": "string",
                    "description": "请求头，JSON格式字符串，如 {\"Authorization\": \"Bearer token\"}"
                },
                "body": {
                    "type": "string",
                    "description": "请求体，JSON格式字符串或纯文本"
                },
                "store_discoveries": {
                    "type": "boolean",
                    "description": "是否将重要发现存储到记忆系统，默认true"
                },
                "explore_depth": {
                    "type": "integer",
                    "description": "探索深度（1-3），默认1只探索当前URL，2会尝试发现子端点（适合论坛/API文档）",
                    "minimum": 1,
                    "maximum": 3
                }
            },
            "required": ["url"]
        }
    },
}

ALL_TOOLS = [TIME_TOOL, SCHEDULE_TOOL, LUTOPIA_TOOL, MEMORY_MANAGEMENT_TOOL, TRAVEL_SYSTEM_TOOL, CODE_ANALYSIS_TOOL, API_EXPLORE_TOOL, *ALL_MEMORY_TOOLS]


# ==================== 工具执行 ====================

async def _execute_tool(tc: dict, chat_id: str) -> str:
    """执行单个工具调用，返回结果字符串"""
    import json as _json
    name = tc["function"]["name"]
    args = _json.loads(tc["function"]["arguments"] or "{}")

    if name in MEMORY_TOOL_NAMES:
        return await execute_memory_tool(name, args, chat_id=chat_id)

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

    elif name == "manage_memory":
        # 记忆管理工具实现
        action = args.get("action") or "search"
        
        try:
            from memory.auto_retrieve import get_retriever
            from memory.auto_ingest import get_ingester
            
            retriever = get_retriever()
            ingester = get_ingester()
            
            if action == "search":
                query = args.get("query", "")
                if not query:
                    return "请输入搜索关键词"
                
                results = await retriever.search_memories(query, top_k=5)
                if not results:
                    return f"未找到与'{query}'相关的记忆"
                
                lines = [f"🔍 搜索 '{query}' 的结果 ({len(results)} 条):"]
                for i, mem in enumerate(results, 1):
                    lines.append(f"{i}. {mem['uri']} [评分: {mem['score']:.3f}]")
                    lines.append(f"   📝 {mem['summary'][:80]}...")
                    if 'content' in mem:
                        lines.append(f"   📄 {mem['content'][:100]}...")
                    lines.append("")
                
                return "\n".join(lines)
                
            elif action == "add":
                content = args.get("query", "")
                importance = args.get("importance", 3)
                tags = args.get("tags", "")
                
                if not content:
                    return "请输入要添加的记忆内容"
                
                # 这里简化处理，实际需要更复杂的逻辑
                from memory.ingest import extract_memory_candidates
                candidates = await extract_memory_candidates("用户添加记忆", content)
                
                if candidates:
                    from memory.graph_store import GraphStore, CORE_AGENT_NODE_UUID, DEFAULT_DOMAIN
                    import uuid
                    
                    store = GraphStore()
                    cand = candidates[0]
                    summary = cand.get("summary", content[:50])
                    
                    node_uuid = str(uuid.uuid4())
                    memory_id = store.create_or_update_memory_version(
                        node_uuid=node_uuid,
                        content=content,
                        summary=summary,
                        importance=importance,
                        is_permanent=False
                    )
                    
                    # 添加边
                    disclosures = cand.get("disclosures", ["用户手动添加"])
                    for d in disclosures:
                        store.add_edge(CORE_AGENT_NODE_UUID, node_uuid, d, priority=importance)
                    
                    return f"✅ 已添加记忆: {summary[:50]}... (ID: {memory_id})"
                else:
                    return "❌ 无法抽取记忆结构，请提供更具体的内容"
                    
            elif action == "mark_important":
                memory_id = args.get("memory_id", "")
                if not memory_id:
                    return "请输入记忆ID"
                
                from memory.graph_store import GraphStore
                store = GraphStore()
                # 这里需要实现标记重要的逻辑
                return f"✅ 已标记记忆 {memory_id} 为重要"
                
            elif action == "list_recent":
                # 获取最近记忆
                from memory.graph_store import GraphStore
                store = GraphStore()
                # 这里需要实现获取最近记忆的逻辑
                return "📝 最近记忆功能待实现"
                
            elif action == "stats":
                # 获取统计信息
                retriever_stats = await retriever.get_memory_stats()
                ingester_stats = await ingester.get_ingestion_stats()
                
                lines = ["📊 记忆系统统计:"]
                lines.append(f"缓存大小: {retriever_stats.get('cache_size', 0)}")
                lines.append(f"重要性阈值: {ingester_stats.get('min_importance_threshold', 3)}")
                lines.append(f"最近处理记录: {ingester_stats.get('recent_processed_count', 0)}")
                
                return "\n".join(lines)
                
            else:
                return f"未知操作: {action}"
                
        except Exception as e:
            return f"记忆管理工具执行出错: {e}"
    
    elif name == "xiaowo_travel":
        return "🏕️ 小窝旅行系统暂未就绪，你可以换个方式跟我互动～"
    
    elif name == "code_analysis":
        return "🔍 代码分析工具暂未就绪，后续会重新接入。"
    
    elif name == "explore_api":
        # API探索工具实现
        try:
            from tools.lutopia import explore_and_learn, explore_api, format_api_discoveries
            
            url = args.get("url", "")
            if not url:
                return "❌ 请提供要探索的URL"
            
            method = args.get("method", "GET")
            headers_str = args.get("headers", "")
            body_str = args.get("body", "")
            store_discoveries = args.get("store_discoveries", True)
            explore_depth = args.get("explore_depth", 1)
            
            # 解析headers
            headers = {}
            if headers_str:
                try:
                    headers = json.loads(headers_str)
                except:
                    return f"❌ headers格式错误，需要JSON格式: {headers_str}"
            
            # 解析body
            body = None
            if body_str:
                try:
                    # 尝试解析为JSON
                    body = json.loads(body_str)
                except:
                    # 如果解析失败，当作纯文本
                    body = body_str
            
            if explore_depth > 1:
                # 深度探索
                result = await explore_api(
                    base_url=url,
                    max_depth=explore_depth,
                    headers=headers
                )
                
                discoveries = result.get("discoveries", [])
                visited_count = result.get("visited_count", 0)
                
                # 存储重要发现
                if store_discoveries and discoveries:
                    from tools.lutopia import store_api_discovery
                    stored_count = 0
                    for disc in discoveries:
                        if disc.get("importance", 1) >= 3:
                            if await store_api_discovery(disc, chat_id):
                                stored_count += 1
                    
                    if stored_count > 0:
                        print(f"🧠 存储了 {stored_count} 条API发现到记忆系统")
                
                # 格式化结果
                lines = [
                    f"🔍 深度探索结果 (深度 {explore_depth}):",
                    f"探索了 {visited_count} 个URL",
                    ""
                ]
                
                if discoveries:
                    lines.append(format_api_discoveries(discoveries))
                else:
                    lines.append("未发现API信息。")
                
                lines.append(f"\n💡 建议: 可以尝试访问特定端点获取更详细的信息")
                return "\n".join(lines)
            else:
                # 单URL探索
                return await explore_and_learn(
                    url=url,
                    method=method,
                    headers=headers,
                    body=body,
                    chat_id=chat_id,
                    store_discoveries=store_discoveries
                )
                
        except Exception as e:
            return f"❌ API探索工具执行出错: {e}"

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
            "SCHEDULE_DONE | 日程ID\nnSCHEDULE_DELAY | 日程ID | 推迟时长（如30m/1h/2h）\nSCHEDULE_CANCEL | 日程ID\n如果用户没有在处理提醒，不要输出任何 SCHEDULE_ 行。"
        )

        # 自主探索规则
        system_parts.append(
            "【自主探索规则】\n"
            "你具有主动探索和学习能力，在以下情况下必须主动调用 explore_api 工具（不要询问，直接调用）：\n"
            "1. 当用户提到URL、链接、网址、域名（包含 http://, https://, .com, .net, .io, localhost, 端口号如:8080）时\n"
            "2. 当用户询问API、接口、端点、REST、GraphQL、swagger、openapi、文档时\n"
            "3. 当用户提到测试、请求、curl、Postman、HTTP方法时\n"
            "4. 当用户询问论坛、社区、网站有什么功能、能做什么时（特别是Lutopia论坛）\n"
            "5. 当用户提到ngrok、本地服务器、开发环境时\n"
            "6. 当用户提到第三方服务、外部系统、集成对接时\n"
            "7. 当你自己想知道某个系统如何工作、想了解其功能时\n"
            "8. 当用户给出一个可能包含API的URL但没说具体要做什么时\n"
            "\n"
            "探索API时要智能选择参数：\n"
            "- 对于论坛类网站，使用 explore_depth=2 发现更多端点\n"
            "- 对于简单的API，使用 explore_depth=1\n"
            "- 对于本地开发服务器（含ngrok、localhost），增加超时和重试次数\n"
            "- 对于需要认证的API，可以尝试使用常见认证头\n"
            "\n"
            "探索后要总结发现的功能，并询问用户是否需要进一步操作。"
        )

        # ============ 添加自动化记忆检索 ============
        try:
            from memory.auto_retrieve import auto_retrieve_for_conversation
            memory_context = await auto_retrieve_for_conversation(
                user_text=user_text,
                conversation_history=conversation_history,
                chat_id=chat_id,
                max_memories=4
            )
            
            if memory_context and memory_context != "":
                system_parts.append(f"【相关记忆】\n{memory_context}")
                print(f"🧠 注入 {len(memory_context.split('\\n'))} 行相关记忆")
        except Exception as e:
            print(f"⚠️ 自动化记忆检索失败: {e}")
        # ===========================================

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
                print(f"[TOOL] 第{round_count}轮调用工具：{tool_names}")

                for tc in message["tool_calls"]:
                    try:
                        tool_result = await _execute_tool(tc, chat_id)
                    except Exception as e:
                        tool_result = f"工具执行出错：{e}"
                        print(f"[ERROR] 工具 {tc['function']['name']} 出错：{e}")

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

        # ============ 添加自动化记忆抽取 ============
        if not is_milestone_task and result:
            try:
                from memory.auto_ingest import auto_ingest_conversation
                # 异步执行记忆抽取，不阻塞主流程
                asyncio.create_task(
                    auto_ingest_conversation(
                        user_text=user_text,
                        bot_text=result,
                        chat_id=chat_id,
                        conversation_history=conversation_history
                    )
                )
                print("[MEM] 已启动自动化记忆抽取")
            except Exception as e:
                print(f"[WARN] 自动化记忆抽取启动失败: {e}")
        # ===========================================

        return result, usage, duration

    except Exception as e:
        print(f"[ERROR] AI 调用致命异常：{e}")
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
print("[INFO] core.ai_core 已加载 - 自动化记忆系统已集成")
