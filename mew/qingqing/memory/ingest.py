"""
记忆 ingest 流水线（核心新增）
============================
把对话总结 / .md 文件 / 外部内容写入 graph_store，统一管理 URI、context、auto_ingested 标记

依赖：mew/memory/graph_store.py 的现有接口
扩展：要求 graph_store 已加 paths.context 字段和 memories.auto_ingested 字段
     （Task 4 的工作；如果还没做，函数会兼容性降级）

设计：
  · 统一的 ingest 入口，所有写记忆的代码都从这里走
  · 记录 auto_ingested 标记，方便事后批量回滚
  · 失败不抛异常，返回 -1
"""

from __future__ import annotations

import logging
import inspect
import os
from typing import List, Optional

log = logging.getLogger(__name__)


# ==================== 单文件 ingest ====================

async def ingest_md_file(
    path: str,
    domain: str,
    context: Optional[List[str]] = None,
    importance: int = 5,
    is_permanent: bool = False,
    auto_ingested: bool = False,
) -> int:
    """
    把一个 .md 文件 ingest 进 graph_store。

    参数：
      path: .md 文件绝对路径
      domain: URI domain（如 "events"、"profile"、"persistent"）
      context: context[] 标签（如 ["emotional", "core_belief"]）
      importance: 1-10
      is_permanent: 是否永久不衰减
      auto_ingested: 是否标记为 AI 自动 ingest（事后可追溯）

    返回：memory_id（成功）或 -1（失败）
    """
    if not os.path.exists(path):
        log.warning(f"[ingest] 文件不存在: {path}")
        return -1

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_content = f.read().strip()
    except Exception as e:
        log.warning(f"[ingest] 读文件失败 {path}: {e}")
        return -1

    if not raw_content:
        log.debug(f"[ingest] 跳过空文件: {path}")
        return -1

    # 生成 summary（首行非空，去 # 等标记，截 50 字）
    summary = _extract_summary(raw_content)

    # URI 路径：domain://相对路径（去掉 .md 后缀）
    rel_path = _build_uri_path(path, domain)

    return await _store_memory(
        content=raw_content,
        summary=summary,
        domain=domain,
        uri_path=rel_path,
        context=context or [],
        importance=importance,
        is_permanent=is_permanent,
        auto_ingested=auto_ingested,
    )


async def reingest_md_file(path: str) -> int:
    """
    重新 ingest 一个 .md 文件。
    旧版本标 deprecated，新版本上位。
    URI 和 context 从已有的 paths 表里查出来复用。
    """
    if not os.path.exists(path):
        log.warning(f"[reingest] 文件不存在: {path}")
        return -1

    # 简单版：从已有的 paths 表里查出 domain 和 context
    try:
        from memory.graph_store import GraphStore
        store = GraphStore()
        existing = _find_existing_path_by_file(store, path)
    except Exception as e:
        log.warning(f"[reingest] 查询已有 path 失败: {e}")
        existing = None

    if existing:
        return await ingest_md_file(
            path=path,
            domain=existing.get("domain", "unknown"),
            context=existing.get("context", []),
            importance=existing.get("importance", 5),
            is_permanent=existing.get("is_permanent", False),
            auto_ingested=False,  # 手动 reingest
        )

    # 没找到旧记录 → 当新文件
    log.info(f"[reingest] 未找到 {path} 的旧记录，按新文件处理")
    return await ingest_md_file(
        path=path,
        domain="unknown",
        context=[],
        auto_ingested=False,
    )


# ==================== 对话总结批量 ingest ====================

async def ingest_conversation_summary(
    chat_id: str,
    summary_items: List[dict],
) -> List[int]:
    """
    把一次对话总结（小模型吐出的多条 memory）批量 ingest。

    每个 item 形如：
      {
        "content": "...",
        "summary": "...",
        "uri": "events://20260428/topic",
        "context": ["emotional"],
        "importance": 7,
        "is_permanent": false
      }

    返回：每条对应的 memory_id 列表，失败的位置是 -1。
    全部以 auto_ingested=True 入库。
    """
    if not summary_items:
        return []

    ids = []
    for item in summary_items:
        try:
            uri = item.get("uri", "")
            domain, uri_path = _split_uri(uri) if uri else ("events", chat_id)

            mid = await _store_memory(
                content=item.get("content", ""),
                summary=item.get("summary", "") or item.get("content", "")[:30],
                domain=domain,
                uri_path=uri_path,
                context=item.get("context", []) or [],
                importance=int(item.get("importance", 5)),
                is_permanent=bool(item.get("is_permanent", False)),
                auto_ingested=True,
            )
            ids.append(mid)
        except Exception as e:
            log.exception(f"[ingest_conv] 单条失败: {e}")
            ids.append(-1)
    return ids


# ==================== 内部：写入 graph_store ====================

async def _store_memory(
    content: str,
    summary: str,
    domain: str,
    uri_path: str,
    context: List[str],
    importance: int,
    is_permanent: bool,
    auto_ingested: bool,
) -> int:
    """
    实际写入 graph_store。
    兼容 graph_store 是否已加 context / auto_ingested 字段两种情况。
    """
    try:
        from memory.graph_store import GraphStore
        store = GraphStore()
    except ImportError as e:
        log.error(f"[ingest] graph_store 不可用: {e}")
        return -1

    if not content or not content.strip():
        return -1

    try:
        # 计算 node_uuid：优先从已有路径查，没有就新生成
        import uuid as _uuid
        from memory.graph_store import CORE_AGENT_NODE_UUID, _uuid5_str
        eid = store.get_edge_id_by_path(domain, uri_path)
        node_uuid = (store.get_child_uuid_by_edge_id(eid) if eid else None) or _uuid5_str(f"{domain}://{uri_path}")

        kwargs = {
            "importance": importance,
            "is_permanent": is_permanent,
            "auto_ingested": auto_ingested,
        }

        memory_id = store.create_or_update_memory_version(
            node_uuid=node_uuid,
            content=content,
            summary=summary,
            **kwargs,
        )

        if not memory_id or memory_id <= 0:
            return -1

        # 添加 path（先创建 edge，再以 edge_id 写 paths）
        try:
            from memory.graph_store import CORE_AGENT_NODE_UUID
            edge_id = store.add_edge(
                CORE_AGENT_NODE_UUID, node_uuid,
                disclosure=summary[:80] or "memory",
                priority=importance,
            )
            sig = inspect.signature(store.add_or_replace_path)
            if "context" in sig.parameters:
                store.add_or_replace_path(
                    domain=domain,
                    path=uri_path,
                    edge_id=edge_id,
                    context=context,
                )
            else:
                store.add_or_replace_path(
                    domain=domain,
                    path=uri_path,
                    edge_id=edge_id,
                )
        except Exception as e:
            log.warning(f"[ingest] add_or_replace_path 失败（不影响 memory 入库）: {e}")

        log.info(
            f"[ingest] ✓ id={memory_id} {domain}://{uri_path} "
            f"ctx={context} imp={importance} perm={is_permanent} "
            f"{'auto' if auto_ingested else 'manual'}"
        )
        return memory_id

    except Exception as e:
        log.exception(f"[ingest] 写入 graph_store 失败: {e}")
        return -1


# ==================== 辅助函数 ====================

def _extract_summary(content: str, max_len: int = 50) -> str:
    """从内容里提取一句简短的 summary"""
    for line in content.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned and len(cleaned) > 2:
            if len(cleaned) > max_len:
                return cleaned[:max_len] + "..."
            return cleaned
    return content[:max_len].replace("\n", " ")


def _build_uri_path(file_path: str, domain: str) -> str:
    """根据文件路径生成 URI path 部分"""
    # 取文件名（无扩展名）
    base = os.path.splitext(os.path.basename(file_path))[0]
    # 取所在目录的最后一段
    parent = os.path.basename(os.path.dirname(file_path))
    if parent and parent != domain:
        return f"{parent}/{base}"
    return base


def _split_uri(uri: str) -> tuple[str, str]:
    """把 'events://20260428/topic' 拆成 ('events', '20260428/topic')"""
    if "://" in uri:
        domain, path = uri.split("://", 1)
        return domain, path
    return "unknown", uri


def _find_existing_path_by_file(store, file_path: str) -> Optional[dict]:
    """从已有的 paths 表里查这个文件对应的记录（简化实现）"""
    # 第一版没做完整的"文件路径 ↔ paths 行"映射
    # 真要做需要在 paths 表加 source_file 字段
    # 暂时返回 None，让上层走"按新文件 ingest"
    return None


# ==================== 旧版 ingest 函数（从 mew/memory/ingest.py 迁移，供 auto_ingest.py 使用） ====================

def _clamp(v):
    try: return max(1, min(5, int(v)))
    except: return 3

def _slugify(p):
    p = re.sub(r"[^a-zA-Z0-9_\\-/]+", "_", (p or "").strip()).strip("_").strip("/")
    return p or "memory/auto"

async def extract_memory_candidates(user_text, bot_text) -> List[dict]:
    from memory.openrouter_client import chat_json
    sp = "你是记忆整理器。输出严格JSON。"
    up = f'用户：{user_text}\n助理：{bot_text}\n输出JSON：{{"worth":true/false,"memories":[{{"summary":"<=120字","content":"<=400字","importance":1-5,"is_permanent":true/false,"disclosures":["触发条件"],"path":"URI path"}}]}}'
    data = await chat_json(system_prompt=sp, user_prompt=up)
    if not isinstance(data, dict) or not data.get("worth"): return []
    cleaned = []
    for m in (data.get("memories") or [])[:2]:
        if not isinstance(m, dict): continue
        ds = m.get("disclosures") or []
        if not ds: continue
        cleaned.append({"summary":str(m.get("summary") or ""),"content":str(m.get("content") or m.get("summary") or ""),"importance":_clamp(m.get("importance")),"is_permanent":bool(m.get("is_permanent")),"disclosures":[str(x).strip() for x in ds if str(x).strip()],"path":str(m.get("path") or "")})
    return cleaned

async def ingest_if_worthy(user_text, bot_text, chat_id=None):
    from memory.graph_store import GraphStore, CORE_AGENT_NODE_UUID, DEFAULT_DOMAIN
    import uuid as _uuid
    store = GraphStore()
    candidates = await extract_memory_candidates(user_text, bot_text)
    for cand in candidates:
        summary = (cand.get("summary") or "").strip()
        content = (cand.get("content") or summary).strip()
        if not summary or not content: continue
        disclosures = (cand.get("disclosures") or [])[:3]
        if not disclosures: continue
        base_path = _slugify(cand.get("path") or summary[:24])
        domain = DEFAULT_DOMAIN
        eid = store.get_edge_id_by_path(domain, base_path)
        node_uuid = (store.get_child_uuid_by_edge_id(eid) if eid else None) or str(_uuid.uuid4())
        store.create_or_update_memory_version(node_uuid, content, summary, _clamp(cand.get("importance")), bool(cand.get("is_permanent")))
        for i, d in enumerate(disclosures, 1):
            edge_id = store.add_edge(CORE_AGENT_NODE_UUID, node_uuid, d, priority=_clamp(cand.get("importance")))
            store.add_or_replace_path(domain, base_path if len(disclosures)==1 else f"{base_path}/d{i}", edge_id)
