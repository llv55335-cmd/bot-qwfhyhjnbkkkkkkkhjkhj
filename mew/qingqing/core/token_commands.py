"""
Token 统计命令
处理 /token 命令，生成统计文本
"""

import os
import json
from config import TOKEN_LOG_FILE


def get_token_stats() -> str:
    if not os.path.exists(TOKEN_LOG_FILE):
        return "📊 还没有 token 使用记录"

    with open(TOKEN_LOG_FILE, "r", encoding="utf-8") as f:
        records = json.load(f)

    if not records:
        return "📊 还没有 token 使用记录"

    total_prompt = sum(r.get("prompt_tokens", 0) for r in records)
    total_completion = sum(r.get("completion_tokens", 0) for r in records)
    total_tokens = total_prompt + total_completion
    total_duration = sum(r.get("duration", 0) for r in records)
    total_cost = sum(r.get("cost", 0.0) for r in records)
    total_cached_tokens = sum(r.get("cached_tokens", 0) for r in records)
    total_cache_write_tokens = sum(r.get("cache_write_tokens", 0) for r in records)
    cache_hit_count = sum(1 for r in records if r.get("cache_hit"))

    by_caller = {}
    for r in records:
        caller = r.get("caller") or r.get("caller_type") or "未知类型"
        info = by_caller.setdefault(caller, {"count": 0, "tokens": 0, "cost": 0.0})
        info["count"] += 1
        info["tokens"] += r.get("prompt_tokens", 0) + r.get("completion_tokens", 0)
        info["cost"] += r.get("cost", 0.0)

    by_category = {}
    for r in records:
        cat = r.get("category", "未分类")
        info = by_category.setdefault(cat, {"count": 0, "tokens": 0, "cost": 0.0})
        info["count"] += 1
        info["tokens"] += r.get("prompt_tokens", 0) + r.get("completion_tokens", 0)
        info["cost"] += r.get("cost", 0.0)

    by_model = {}
    for r in records:
        m = r.get("model", "未知模型")
        info = by_model.setdefault(m, {"count": 0, "tokens": 0, "cost": 0.0})
        info["count"] += 1
        info["tokens"] += r.get("prompt_tokens", 0) + r.get("completion_tokens", 0)
        info["cost"] += r.get("cost", 0.0)

    top_callers = sorted(by_caller.items(), key=lambda x: x[1]["cost"], reverse=True)[:3]
    avg_speed = round(total_completion / total_duration, 1) if total_duration > 0 else 0

    lines = [
        "📊 Token 使用统计",
        "================",
        f"📈 上载总计：{total_prompt}",
        f"📉 下载总计：{total_completion}",
        f"📊 总计：{total_tokens}",
        f"⏱️ 总耗时：{round(total_duration, 1)}s",
        f"🚀 平均速度：{avg_speed} tk/s",
        f"💰 总费用：{total_cost:.6f} USD（约合人民币≈{total_cost*7:.2f}）",
        f"📅 记录数：{len(records)}",
        "",
        "📦 缓存情况：",
        f"- 命中次数：{cache_hit_count}",
        f"- 命中 token：{total_cached_tokens}",
        f"- 写入缓存 token：{total_cache_write_tokens}",
    ]

    if top_callers:
        lines.append("")
        lines.append("🔥 最烧钱的调用类型：")
        for caller, info in top_callers:
            lines.append(f"- {caller}：{info['count']} 次，{info['tokens']} tokens，{info['cost']:.6f} USD")

    if by_category:
        lines.append("")
        lines.append("📂 按分类：")
        for cat, info in sorted(by_category.items(), key=lambda x: x[1]["cost"], reverse=True):
            lines.append(f"- {cat}：{info['count']} 次，{info['tokens']} tokens，{info['cost']:.6f} USD")

    if by_model:
        lines.append("")
        lines.append("🤖 按模型：")
        for m, info in sorted(by_model.items(), key=lambda x: x[1]["cost"], reverse=True):
            lines.append(f"- {m}：{info['count']} 次，{info['tokens']} tokens，{info['cost']:.6f} USD")

    return "\n".join(lines)
