"""
文件操作 HTTP 路由
================
GET 路由保留兼容（list/read/search/snapshot）
写操作既支持 POST（推荐）也保留 GET（兼容旧 MCP）
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Query
from fastapi.responses import PlainTextResponse

from services import files as files_svc

router = APIRouter()


# ==================== 读 ====================

@router.get("/list", response_class=PlainTextResponse)
async def list_files(path: str = ""):
    return files_svc.api_list(path)


@router.get("/read", response_class=PlainTextResponse)
async def read_file(path: str = ""):
    return files_svc.api_read(path)


@router.get("/search", response_class=PlainTextResponse)
async def search_files(
    query: str = Query(..., description="搜索关键词"),
    path: str = "",
    max_results: int = 50,
):
    return files_svc.api_search(query, path, max_results)


@router.get("/snapshot", response_class=PlainTextResponse)
async def snapshot():
    return files_svc.api_snapshot()


# ==================== 写（POST 推荐）====================

@router.post("/write", response_class=PlainTextResponse)
async def write_file(payload: dict = Body(...)):
    path = payload.get("path", "")
    content = payload.get("content", "")
    return files_svc.api_write(path, content)


@router.post("/diary", response_class=PlainTextResponse)
async def write_diary(payload: dict = Body(...)):
    path = payload.get("path", "")
    content = payload.get("content", "")
    return files_svc.api_diary(path, content)


@router.post("/delete", response_class=PlainTextResponse)
async def delete_file(payload: dict = Body(...)):
    path = payload.get("path", "")
    return files_svc.api_delete(path)


@router.post("/rename", response_class=PlainTextResponse)
async def rename_file(payload: dict = Body(...)):
    old_path = payload.get("old_path", "")
    new_path = payload.get("new_path", "")
    return files_svc.api_rename(old_path, new_path)


# ==================== 写（GET 兼容，6 个月后删）====================
# 旧版 MCP / 浏览器收藏夹可能用 GET，先保留

@router.get("/write", response_class=PlainTextResponse)
async def write_file_get(path: str = "", content: str = ""):
    return files_svc.api_write(path, content)


@router.get("/diary", response_class=PlainTextResponse)
async def write_diary_get(path: str = "", content: str = ""):
    return files_svc.api_diary(path, content)


@router.get("/delete", response_class=PlainTextResponse)
async def delete_file_get(path: str = ""):
    return files_svc.api_delete(path)


@router.get("/rename", response_class=PlainTextResponse)
async def rename_file_get(old_path: str = "", new_path: str = ""):
    return files_svc.api_rename(old_path, new_path)
