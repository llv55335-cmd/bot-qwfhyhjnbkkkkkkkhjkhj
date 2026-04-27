"""
检索模块 v2
- 使用新版 graph_store（向量 + token 融合）
- 检索后自动更新共现矩阵
- 衰减加权
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from .graph_store import GraphStore


def _decay(importance, is_perm, created_at_iso):
    """旧版衰减，仅在 decay_score 缺失时作兜底"""
    try:
        dt = datetime.fromisoformat(created_at_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        return float(importance)
    days = max(0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
    return float(importance) * ((0.99 if is_perm else 0.9) ** days)


async def retrieve_related_memories(
    query_text: str,
    recent_messages: Optional[List[dict]] = None,
    top_k: int = 6,
) -> str:
    store = GraphStore()

    # 拼入最近对话，增强 query 语义
    ctx = query_text
    if recent_messages:
        ctx = (
            "\n".join(
                f"{m.get('role', '')}: {m.get('content', '')}"
                for m in recent_messages[-8:]
            )
            + f"\nUSER: {query_text}"
        )

    candidates = store.fetch_alias_candidates(query_text=ctx, max_candidates=25)
    if not candidates:
        return ""

    top = candidates[:top_k]

    # 更新使用记录
    hit_ids: List[int] = []
    for p in top:
        try:
            mid = int(p["memory_id"])
            store.mark_memory_used(mid)
            hit_ids.append(mid)
        except Exception:
            pass

    # 更新共现矩阵
    if len(hit_ids) >= 2:
        try:
            store.update_co_occurrence(hit_ids)
        except Exception:
            pass

    # 组装上下文文本
    blocks = ["【可触发相关记忆】"]
    for i, p in enumerate(top, 1):
        score = round(p.get("base_score", 0), 3)
        blocks.append(
            f"{i}. {p['uri']}  [score={score}]\n"
            f"   - summary: {p.get('summary') or p.get('content')}"
        )

    return "\n".join(blocks)
