"""
Trilium ETAPI 封装
负责：创建/更新周总结笔记到本地 Trilium
"""

from __future__ import annotations
import httpx
from datetime import datetime
from typing import Optional
from config import TRILIUM_API_TOKEN

BASE = "http://localhost:8080/etapi"
HEADERS = {"Authorization": TRILIUM_API_TOKEN}
TIMEOUT = 10.0

# Trilium 里存放周总结的父节点 ID
# 第一次运行后会自动找或创建，也可以手动填
WEEKLY_PARENT_NOTE_ID = "root"


async def _get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(f"{BASE}{path}", headers=HEADERS)
        r.raise_for_status()
        return r.json()


async def _post(path: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{BASE}{path}", headers=HEADERS, json=payload)
        r.raise_for_status()
        return r.json()


async def _put_content(note_id: str, content: str) -> None:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.put(
            f"{BASE}/notes/{note_id}/content",
            headers={**HEADERS, "Content-Type": "text/html"},
            content=content.encode("utf-8"),
        )
        r.raise_for_status()


async def ping() -> bool:
    """测试连通性"""
    try:
        await _get("/app-info")
        return True
    except Exception:
        return False


async def create_note(
    title: str,
    content: str,
    parent_note_id: str = WEEKLY_PARENT_NOTE_ID,
    note_type: str = "text",
) -> Optional[str]:
    """
    创建笔记，返回 note_id
    content 支持 HTML 或纯文本（纯文本会自动包一层 <p>）
    """
    try:
        # 纯文本转 HTML
        if not content.strip().startswith("<"):
            html = "<br>".join(
                f"<p>{line}</p>" if line.strip() else "<p></p>"
                for line in content.splitlines()
            )
        else:
            html = content

        data = await _post("/create-note", {
            "parentNoteId": parent_note_id,
            "title": title,
            "type": note_type,
            "content": html,
        })
        note_id = data.get("note", {}).get("noteId")
        print(f"✅ Trilium 笔记创建：{title}（id={note_id}）")
        return note_id
    except Exception as e:
        print(f"❌ Trilium 创建失败：{e}")
        return None


async def update_note_content(note_id: str, content: str) -> bool:
    """更新笔记内容"""
    try:
        if not content.strip().startswith("<"):
            html = "<br>".join(
                f"<p>{line}</p>" if line.strip() else "<p></p>"
                for line in content.splitlines()
            )
        else:
            html = content
        await _put_content(note_id, html)
        print(f"✅ Trilium 笔记更新：{note_id}")
        return True
    except Exception as e:
        print(f"❌ Trilium 更新失败：{e}")
        return False


async def search_note_by_title(title: str) -> Optional[str]:
    """按标题搜索，返回第一个匹配的 note_id"""
    try:
        data = await _get(f"/notes?search={title}")
        results = data.get("results", [])
        if results:
            return results[0].get("noteId")
        return None
    except Exception:
        return None


async def push_weekly_summary(week_str: str, content: str) -> Optional[str]:
    """
    推送周总结到 Trilium
    week_str: 如 "2026-W13"
    先搜索是否已有同名笔记，有则更新，没有则新建
    返回 note_id
    """
    title = f"周总结 {week_str}"
    existing_id = await search_note_by_title(title)
    if existing_id:
        ok = await update_note_content(existing_id, content)
        return existing_id if ok else None
    else:
        return await create_note(title, content)
