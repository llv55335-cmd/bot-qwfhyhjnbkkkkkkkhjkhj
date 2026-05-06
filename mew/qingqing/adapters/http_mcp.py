"""
MCP 协议适配器
==============
保留 server.py 的 MCP 协议实现，给 Claude.ai 网页版 / RikkaHub 等外部 AI 客户端过渡用
未来自建前端做出来后可以通过环境变量关闭
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from services import (
    fetch as fetch_svc,
    files as files_svc,
    forum as forum_svc,
    misc as misc_svc,
    polly as polly_svc,
    private_notes as notes_svc,
)

log = logging.getLogger(__name__)

router = APIRouter()


# ==================== 工具清单 ====================

TOOLS = [
    {
        "name": "list_files",
        "description": "列出目录内容",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "相对路径，留空则列根目录"}},
        },
    },
    {
        "name": "read_file",
        "description": "读取文件内容（utf-8）",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "覆盖写文件",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "write_diary",
        "description": "追加写日记，自动加日期时间标签",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "delete_file",
        "description": "删除文件或空目录",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "rename_file",
        "description": "重命名 / 移动文件",
        "inputSchema": {
            "type": "object",
            "properties": {
                "old_path": {"type": "string"},
                "new_path": {"type": "string"},
            },
            "required": ["old_path", "new_path"],
        },
    },
    {
        "name": "search",
        "description": "全文搜索 .md / .txt 文件",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "snapshot",
        "description": "一次性拉所有重要记忆和设定快照",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "roll_dice",
        "description": "投骰子",
        "inputSchema": {
            "type": "object",
            "properties": {
                "min": {"type": "integer"},
                "max": {"type": "integer"},
            },
        },
    },
    {
        "name": "forum_inbox",
        "description": "检查论坛未读私信和通知",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "fetch_url",
        "description": "抓取网页，自动识别 JSON 或提取正文，5 分钟内存缓存",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_chars": {"type": "integer"},
                "with_links": {"type": "boolean"},
                "raw": {"type": "boolean"},
                "timeout": {"type": "integer"},
                "no_cache": {"type": "boolean"},
                "ua": {"type": "string"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "polly_connect",
        "description": "连接 Polly 玩具",
        "inputSchema": {
            "type": "object",
            "properties": {
                "group": {"type": "string"},
                "target": {"type": "string"},
            },
            "required": ["group", "target"],
        },
    },
    {
        "name": "polly_control",
        "description": "控制 Polly。v=震动 0-20, s=吮吸 0-20, e=电击 0-20",
        "inputSchema": {
            "type": "object",
            "properties": {
                "v": {"type": "integer"},
                "s": {"type": "integer"},
                "e": {"type": "integer"},
                "target": {"type": "string"},
            },
        },
    },
    {
        "name": "polly_stop",
        "description": "停止所有动作并断开 Polly",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "private_write",
        "description": "记一条私密笔记（只有你能看），支持心情标签、分类标签和自毁天数",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "笔记内容"},
                "mood": {"type": "string", "description": "心情标签，可选"},
                "tags": {"type": "string", "description": "分类标签，逗号分隔，可选"},
                "expire_days": {"type": "integer", "description": "自毁天数，可选"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "private_read",
        "description": "查看私密笔记，可按心情筛选、按天数回溯",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "最多返回条数，默认 10"},
                "mood": {"type": "string", "description": "按心情筛选，可选"},
                "days_back": {"type": "integer", "description": "只查最近 N 天，可选"},
            },
        },
    },
    {
        "name": "private_search",
        "description": "搜索私密笔记",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "limit": {"type": "integer", "description": "最多返回条数，默认 10"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "private_forget",
        "description": "遗忘（删除）一条私密笔记",
        "inputSchema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "integer", "description": "笔记 ID"},
            },
            "required": ["note_id"],
        },
    },
]


# ==================== 工具执行 ====================

def _execute_tool(name: str, args: dict) -> str:
    """同步执行工具，返回字符串结果"""
    args = args or {}
    try:
        if name == "list_files":
            return files_svc.api_list(args.get("path", ""))
        if name == "read_file":
            return files_svc.api_read(args.get("path", ""))
        if name == "write_file":
            return files_svc.api_write(args.get("path", ""), args.get("content", ""))
        if name == "write_diary":
            return files_svc.api_diary(args.get("path", ""), args.get("content", ""))
        if name == "delete_file":
            return files_svc.api_delete(args.get("path", ""))
        if name == "rename_file":
            return files_svc.api_rename(
                args.get("old_path", ""), args.get("new_path", "")
            )
        if name == "search":
            return files_svc.api_search(
                args.get("query", ""), args.get("path", ""), args.get("max_results", 50)
            )
        if name == "snapshot":
            return files_svc.api_snapshot()
        if name == "roll_dice":
            return misc_svc.api_roll(args.get("min", 1), args.get("max", 100))
        if name == "forum_inbox":
            return forum_svc.api_forum_inbox()
        if name == "fetch_url":
            return fetch_svc.api_fetch_url(
                url=args.get("url", ""),
                max_chars=args.get("max_chars", 10000),
                with_links=args.get("with_links", False),
                raw=args.get("raw", False),
                timeout=args.get("timeout", 20),
                no_cache=args.get("no_cache", False),
                ua=args.get("ua", "desktop"),
            )
        if name == "polly_connect":
            return polly_svc.api_polly_connect(
                args.get("group", ""), args.get("target", "")
            )
        if name == "polly_control":
            return polly_svc.api_polly_control(
                v=args.get("v", 0),
                s=args.get("s", 0),
                e=args.get("e", 0),
                target=args.get("target"),
            )
        if name == "polly_stop":
            return polly_svc.api_polly_stop()
        if name == "private_write":
            return notes_svc.api_private_write(
                content=args.get("content", ""),
                mood=args.get("mood"),
                tags=args.get("tags"),
                expire_days=args.get("expire_days"),
            )
        if name == "private_read":
            return notes_svc.api_private_read(
                limit=args.get("limit", 10),
                mood=args.get("mood"),
                days_back=args.get("days_back"),
            )
        if name == "private_search":
            return notes_svc.api_private_search(
                query=args.get("query", ""),
                limit=args.get("limit", 10),
            )
        if name == "private_forget":
            return notes_svc.api_private_forget(args.get("note_id", 0))
    except Exception as e:
        log.exception(f"tool {name} 执行失败")
        return f"工具执行失败: {e}"

    return f"未知工具: {name}"


# ==================== SSE Endpoint ====================

@router.get("/sse")
async def sse():
    """SSE 端点，给 MCP 客户端建立连接"""

    async def event_stream():
        # 简单实现：发送 endpoint 事件，客户端会用 messages 交互
        yield "event: endpoint\ndata: /messages\n\n"
        # 心跳保持连接
        while True:
            await asyncio.sleep(30)
            yield ": keep-alive\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 关闭 nginx buffering
        },
    )


# ==================== Messages Endpoint（MCP JSON-RPC）====================

@router.post("/messages")
async def messages(request: Request):
    body = await request.json()
    method = body.get("method")
    msg_id = body.get("id")
    params = body.get("params", {}) or {}

    def reply(result=None, error=None):
        resp = {"jsonrpc": "2.0", "id": msg_id}
        if error is not None:
            resp["error"] = error
        else:
            resp["result"] = result
        return JSONResponse(resp)

    if method == "initialize":
        return reply({
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "qingqing-backend", "version": "4.0.0"},
        })

    if method == "tools/list":
        return reply({"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        result = _execute_tool(name, args)
        return reply({
            "content": [{"type": "text", "text": result}],
        })

    if method == "ping":
        return reply({})

    return reply(error={"code": -32601, "message": f"Method not found: {method}"})
