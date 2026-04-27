"""
周度文件管理
负责：周对话、周总结、周 token 消耗的分文件存储
文件命名：week_chat_2026-W13.json / week_summary_2026-W13.json / week_token_2026-W13.json
"""

from __future__ import annotations
import json
import os
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from config import DATA_DIR

WEEK_DIR = os.path.join(DATA_DIR, "weekly")


def _ensure_dir():
    os.makedirs(WEEK_DIR, exist_ok=True)


def _week_str(dt: date = None) -> str:
    """返回如 2026-W13"""
    d = dt or date.today()
    return f"{d.year}-W{d.isocalendar()[1]:02d}"


def _path(prefix: str, week: str = None) -> str:
    _ensure_dir()
    w = week or _week_str()
    return os.path.join(WEEK_DIR, f"week_{prefix}_{w}.json")


# ── 周对话 ──────────────────────────────────────────────

def append_week_chat(role: str, content: str, week: str = None):
    """追加一条对话到本周文件"""
    p = _path("chat", week)
    records = _load(p)
    records.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "role": role,
        "content": content,
    })
    _save(p, records)


def get_week_chat(week: str = None) -> List[Dict]:
    return _load(_path("chat", week))


# ── 周总结 ──────────────────────────────────────────────

def save_week_summary(summary: Dict[str, Any], week: str = None):
    """保存周总结（覆盖写）"""
    p = _path("summary", week)
    _save(p, summary)
    print(f"✅ 周总结已存：{p}")


def get_week_summary(week: str = None) -> Optional[Dict]:
    p = _path("summary", week)
    data = _load(p)
    return data if data else None


# ── 周 token ────────────────────────────────────────────

def append_week_token(record: Dict[str, Any], week: str = None):
    """追加一条 token 记录到本周文件"""
    p = _path("token", week)
    records = _load(p)
    records.append(record)
    _save(p, records)


def get_week_token(week: str = None) -> List[Dict]:
    return _load(_path("token", week))


def get_week_token_stats(week: str = None) -> Dict[str, Any]:
    """汇总本周 token 消耗"""
    records = get_week_token(week)
    if not records:
        return {"total": 0, "prompt": 0, "completion": 0, "cost": 0.0, "count": 0}
    return {
        "count": len(records),
        "prompt": sum(r.get("prompt_tokens", 0) for r in records),
        "completion": sum(r.get("completion_tokens", 0) for r in records),
        "total": sum(r.get("total", 0) for r in records),
        "cost": round(sum(r.get("cost", 0.0) for r in records), 6),
        "cached": sum(r.get("cached_tokens", 0) for r in records),
    }


# ── 工具 ────────────────────────────────────────────────

def list_weeks() -> List[str]:
    """列出所有有数据的周"""
    _ensure_dir()
    weeks = set()
    for f in os.listdir(WEEK_DIR):
        if f.startswith("week_") and f.endswith(".json"):
            parts = f.replace(".json", "").split("_")
            if len(parts) >= 3:
                weeks.add(parts[-1])
    return sorted(weeks, reverse=True)


def current_week() -> str:
    return _week_str()


def _load(path: str) -> Any:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(path: str, data: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
