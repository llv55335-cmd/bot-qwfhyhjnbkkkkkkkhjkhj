"""
Token 记录模块
记录每次 API 调用的 token 使用情况
"""

import os
import json
from datetime import datetime
from config import TOKEN_LOG_FILE
from core.weekly_store import append_week_token


async def log_token_usage(
    caller: str,
    prompt_tokens: int,
    completion_tokens: int,
    duration: float = 0,
    cost: float = 0.0,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
    model: str = "",
    category: str = "对话",
):
    records = []
    if os.path.exists(TOKEN_LOG_FILE):
        with open(TOKEN_LOG_FILE, "r", encoding="utf-8") as f:
            try:
                records = json.load(f)
            except Exception:
                records = []

    total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "caller": caller,
        "category": category,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total": total_tokens,
        "duration": duration,
        "cost": cost,
        "cached_tokens": cached_tokens,
        "cache_write_tokens": cache_write_tokens,
        "cache_hit": (cached_tokens or 0) > 0,
    }
    records.append(record)

    with open(TOKEN_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(
        f"✅ Token 记录：[{category}] {caller} ({model}), "
        f"↑{prompt_tokens} ↓{completion_tokens}, "
        f"耗时 {duration}s, cost={cost}"
    )

    append_week_token(record)