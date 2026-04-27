"""写入 ingest - 保留现状"""
from __future__ import annotations
import re, uuid
from typing import Any, Dict, List
from .graph_store import CORE_AGENT_NODE_UUID, DEFAULT_DOMAIN, GraphStore
from .openrouter_client import chat_json

def _clamp(v):
    try: return max(1, min(5, int(v)))
    except: return 3

def _slugify(p):
    p = re.sub(r"[^a-zA-Z0-9_\\-/]+", "_", (p or "").strip()).strip("_").strip("/")
    return p or "memory/auto"

async def extract_memory_candidates(user_text, bot_text) -> List[Dict[str, Any]]:
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
        node_uuid = (store.get_child_uuid_by_edge_id(eid) if eid else None) or str(uuid.uuid4())
        store.create_or_update_memory_version(node_uuid, content, summary, _clamp(cand.get("importance")), bool(cand.get("is_permanent")))
        for i, d in enumerate(disclosures, 1):
            edge_id = store.add_edge(CORE_AGENT_NODE_UUID, node_uuid, d, priority=_clamp(cand.get("importance")))
            store.add_or_replace_path(domain, base_path if len(disclosures)==1 else f"{base_path}/d{i}", edge_id)
