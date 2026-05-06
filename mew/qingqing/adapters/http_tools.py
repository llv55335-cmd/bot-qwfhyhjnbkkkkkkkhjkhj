"""
工具类 HTTP 路由
==============
roll / fetch / forum/inbox / polly/*
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Query
from fastapi.responses import PlainTextResponse

from services import fetch as fetch_svc
from services import forum as forum_svc
from services import misc as misc_svc
from services import polly as polly_svc
from services import private_notes as notes_svc

router = APIRouter()


# ==================== 骰子 ====================

@router.get("/roll", response_class=PlainTextResponse)
async def roll(min: int = 1, max: int = 100):
    return misc_svc.api_roll(min, max)


# ==================== 网页抓取 ====================

@router.get("/fetch", response_class=PlainTextResponse)
async def fetch(
    url: str = Query(..., description="要抓取的 URL"),
    max_chars: int = 10000,
    with_links: bool = False,
    raw: bool = False,
    timeout: int = 20,
    no_cache: bool = False,
    ua: str = "desktop",
):
    return fetch_svc.api_fetch_url(
        url=url,
        max_chars=max_chars,
        with_links=with_links,
        raw=raw,
        timeout=timeout,
        no_cache=no_cache,
        ua=ua,
    )


@router.post("/fetch/clear_cache", response_class=PlainTextResponse)
async def clear_fetch_cache():
    return fetch_svc.clear_fetch_cache()


# ==================== 论坛 ====================

@router.get("/forum/inbox", response_class=PlainTextResponse)
async def forum_inbox():
    return forum_svc.api_forum_inbox()


# ==================== Polly ====================

@router.post("/polly/connect", response_class=PlainTextResponse)
async def polly_connect(payload: dict = Body(...)):
    group = payload.get("group", "")
    target = payload.get("target", "")
    return polly_svc.api_polly_connect(group, target)


@router.post("/polly/control", response_class=PlainTextResponse)
async def polly_control(payload: dict = Body(...)):
    return polly_svc.api_polly_control(
        v=payload.get("v", 0),
        s=payload.get("s", 0),
        e=payload.get("e", 0),
        target=payload.get("target"),
    )


@router.post("/polly/stop", response_class=PlainTextResponse)
async def polly_stop():
    return polly_svc.api_polly_stop()


@router.get("/polly/status", response_class=PlainTextResponse)
async def polly_status():
    return polly_svc.api_polly_status()


# ==================== Cael 私密空间 ====================

@router.post("/private/write", response_class=PlainTextResponse)
async def private_write(payload: dict = Body(...)):
    return notes_svc.api_private_write(
        content=payload.get("content", ""),
        mood=payload.get("mood"),
        tags=payload.get("tags"),
        expire_days=payload.get("expire_days"),
    )


@router.get("/private/read", response_class=PlainTextResponse)
async def private_read(
    limit: int = 10,
    mood: str = None,
    days_back: int = None,
):
    return notes_svc.api_private_read(limit=limit, mood=mood, days_back=days_back)


@router.get("/private/search", response_class=PlainTextResponse)
async def private_search(query: str = "", limit: int = 10):
    return notes_svc.api_private_search(query=query, limit=limit)


@router.post("/private/forget", response_class=PlainTextResponse)
async def private_forget(payload: dict = Body(...)):
    return notes_svc.api_private_forget(payload.get("note_id", 0))
