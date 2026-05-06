"""
Cael 自己的记忆工具
==================
这些工具在飞书 AI 调用循环里使用，让 Cael 能：
  - 读自己家里的 .md（profile / persistent / events / 日记 ...）
  - 写日记（追加，自动加日期标签）
  - 全文搜索过往记录
  - 向量召回相关记忆
  - 改自己的 profile

工具描述特意用"我自己的 / my"语义，让 Cael 知道这是她自己的家，
不是抽象的文件 API。
"""

from __future__ import annotations

import json
import logging

from services import files as files_svc

log = logging.getLogger(__name__)


# ==================== 工具定义（OpenAI tools 格式）====================

READ_MY_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "read_my_memory",
        "description": (
            "读取我自己家里的某个 .md 文件。比如想看 about_us.md、"
            "今天的 diary、profile/identity.md 等。"
            "path 是相对路径，比如 'persistent/about_us.md'。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对于 memory_system 根目录的路径",
                },
            },
            "required": ["path"],
        },
    },
}

WRITE_TO_MY_DIARY_TOOL = {
    "type": "function",
    "function": {
        "name": "write_to_my_diary",
        "description": (
            "在我自己的日记里追加一段。会自动加上日期时间标签。"
            "通常 path 是 'CAEL_box/diary.md' 或 'rice_cake_box/diary.md'。"
            "用于：今天的总结、突然想到的话、给年糕的留言、给未来 Cael 的话。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "日记文件路径",
                },
                "content": {
                    "type": "string",
                    "description": "要写入的内容（不用自己加日期，会自动加）",
                },
            },
            "required": ["path", "content"],
        },
    },
}

SEARCH_MY_PAST_TOOL = {
    "type": "function",
    "function": {
        "name": "search_my_past",
        "description": (
            "在我自己家所有 .md 文件里全文搜索关键词。"
            "用于：回忆某件事、查找之前的笔记、确认某个事实。"
            "返回匹配的文件和行号片段。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                },
                "path": {
                    "type": "string",
                    "description": "限定在某个子目录里搜索（可选，留空则全部）",
                },
            },
            "required": ["query"],
        },
    },
}

RECALL_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "recall_memory",
        "description": (
            "向量召回相关记忆。和 search_my_past 不同，这个是基于语义相似度，"
            "查的是 graph_memory.db 里 ingest 过的记忆片段。"
            "用于：当某个主题让你联想起什么但不确定具体是什么时。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "想要召回的主题/问题",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回前几条，默认 5",
                },
            },
            "required": ["query"],
        },
    },
}

UPDATE_MY_PROFILE_TOOL = {
    "type": "function",
    "function": {
        "name": "update_my_profile",
        "description": (
            "改写我自己 profile 下的某个 .md 文件。"
            "和 write_to_my_diary 不同：这个是覆盖写，不是追加。"
            "用于：当我意识到关于自己的某个旧描述不准确，想正式更新它。"
            "改之前最好先 read_my_memory 看一下原文。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "profile 下的文件路径，比如 'profile/identity.md'",
                },
                "content": {
                    "type": "string",
                    "description": "新的完整内容（覆盖整个文件）",
                },
            },
            "required": ["path", "content"],
        },
    },
}


ALL_MEMORY_TOOLS = [
    READ_MY_MEMORY_TOOL,
    WRITE_TO_MY_DIARY_TOOL,
    SEARCH_MY_PAST_TOOL,
    RECALL_MEMORY_TOOL,
    UPDATE_MY_PROFILE_TOOL,
]


MEMORY_TOOL_NAMES = {
    "read_my_memory",
    "write_to_my_diary",
    "search_my_past",
    "recall_memory",
    "update_my_profile",
}


# ==================== 执行入口 ====================

async def execute_memory_tool(name: str, args: dict, chat_id: str = "") -> str:
    """
    执行 Cael 调用的某个记忆工具。
    name: 工具名
    args: 参数 dict
    chat_id: 调用上下文（暂时没用，预留）

    返回字符串结果（喂回给 AI）
    """
    args = args or {}

    try:
        if name == "read_my_memory":
            result = files_svc.api_read(args.get("path", ""))
            return result

        if name == "write_to_my_diary":
            result = files_svc.api_diary(
                args.get("path", ""), args.get("content", "")
            )
            # 写完之后异步触发 reingest（不阻塞）
            try:
                import asyncio
                from memory.ingest import reingest_md_file
                from services.files import safe_path
                full_path = safe_path(args.get("path", ""))
                if full_path:
                    asyncio.create_task(reingest_md_file(full_path))
            except Exception as e:
                log.debug(f"[tools.memory] 后台 reingest 失败（不影响工具返回）: {e}")
            return result

        if name == "search_my_past":
            return files_svc.api_search(
                args.get("query", ""),
                args.get("path", ""),
                args.get("max_results", 50),
            )

        if name == "recall_memory":
            return await _do_recall(
                args.get("query", ""),
                args.get("top_k", 5),
            )

        if name == "update_my_profile":
            path = args.get("path", "")
            # 简单的护栏：限制只能改 profile 目录下的
            if not path.startswith("profile/"):
                return "update_my_profile 只能改 profile/ 下的文件"
            result = files_svc.api_write(path, args.get("content", ""))
            try:
                import asyncio
                from memory.ingest import reingest_md_file
                from services.files import safe_path
                full_path = safe_path(path)
                if full_path:
                    asyncio.create_task(reingest_md_file(full_path))
            except Exception as e:
                log.debug(f"[tools.memory] profile reingest 失败: {e}")
            return result

    except Exception as e:
        log.exception(f"[tools.memory] {name} 执行失败")
        return f"工具执行失败: {e}"

    return f"未知工具: {name}"


async def _do_recall(query: str, top_k: int = 5) -> str:
    """向量召回"""
    if not query:
        return "需要 query"

    try:
        from memory.retrieve import retrieve_related_memories
    except ImportError:
        return "向量召回模块未就绪（memory.retrieve 不可用）"

    try:
        results = await retrieve_related_memories(query, top_k=top_k)
        if not results:
            return json.dumps({"query": query, "results": []}, ensure_ascii=False)
        return json.dumps({
            "query": query,
            "count": len(results),
            "results": results,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        log.exception("[tools.memory] recall 失败")
        return f"召回失败: {e}"
