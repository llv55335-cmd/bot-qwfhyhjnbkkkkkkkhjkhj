"""
OpenRouter 调用封装（用于 memory 的 ingest/retrieve/maintenance）
不依赖 ai_core，避免循环依赖
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from config import API_URL, KEY, MODEL_NAME


def _extract_json_object(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    return m.group(0) if m else None


async def chat_json(system_prompt: str, user_prompt: str, timeout_s: float = 120.0) -> Dict[str, Any]:
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            API_URL,
            headers={"Authorization": f"Bearer {KEY}"},
            json={"model": MODEL_NAME, "messages": messages},
        )

    if resp.status_code != 200:
        raise RuntimeError(f"OpenRouter error {resp.status_code}: {resp.text}")

    data = resp.json()
    content = data["choices"][0]["message"]["content"].strip()

    json_text = _extract_json_object(content)
    if not json_text:
        raise ValueError(f"Failed to extract JSON from model output: {content[:500]}")

    return json.loads(json_text)
