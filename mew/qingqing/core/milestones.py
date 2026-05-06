"""
大事记模块
负责：记录重要对话、权重衰减、检索高权重记忆
"""

import os
import json
import re
from datetime import datetime

from config import (
    MILESTONE_FILE,
    PERMANENT_DECAY_RATE,
    AUTO_DECAY_RATE,
    IMPORTANT_MEMORY_TOP_COUNT,
    IMPORTANT_MEMORY_RECENT_COUNT,
)
from core.ai_core import call_ai


async def update_milestones(user_text: str, bot_text: str):
    stories = []
    if os.path.exists(MILESTONE_FILE):
        with open(MILESTONE_FILE, "r", encoding="utf-8") as f:
            stories = json.load(f)

    decision_prompt = f"""
    判断以下对话：
    卿卿："{user_text}"
    你："{bot_text}"

    请做三件事：
    1. 这段对话值不值得记？如果值得，用一句具体的话概括（20字内，必须包含具体内容，禁止输出"值得记录"这种空话）
    2. 如果值得，它是"永久"还是"普通"
    3. 如果是永久，重要程度（1-10）

    严格只输出一行，格式为：具体概括内容 | 类型 | 重要程度
    如果不值得记，严格只输出：IGNORE
    不要输出任何分析、解释或额外文字。
    """

    result_tuple = await call_ai(
        decision_prompt, is_milestone_task=True, caller="大事记判断"
    )
    result = result_tuple[0] if result_tuple else None

    if result and "IGNORE" not in result:
        parts = result.split("|")
        content = parts[0].strip()

        # 过滤无意义的概括
        if content in ("值得记录", "值得", "值得记", "记录"):
            print(f"📖 概括内容无意义，跳过：{content}")
            return

        record_type = parts[1].strip() if len(parts) > 1 else "普通"
        raw_importance = parts[2].strip() if len(parts) > 2 else "5"
        importance_match = re.search(r"\d+", raw_importance)
        importance = int(importance_match.group()) if importance_match else 5

        stories.append(
            {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "event": content,
                "type": "permanent" if record_type == "永久" else "auto",
                "importance": importance,
            }
        )

        if record_type == "普通":
            auto_stories = [s for s in stories if s["type"] == "auto"][-40:]
            permanent_stories = [s for s in stories if s["type"] == "permanent"]
            stories = permanent_stories + auto_stories

        with open(MILESTONE_FILE, "w", encoding="utf-8") as f:
            json.dump(stories, f, ensure_ascii=False, indent=2)

        print(f"📖 记下了：{content}（{record_type}，重要程度{importance}）")
    else:
        print(f"📖 不值得记：{result}")


def get_weight(record, current_date):
    date_obj = datetime.strptime(record["date"], "%Y-%m-%d")
    days_ago = (current_date - date_obj).days

    if record["type"] == "permanent":
        return record["importance"] * (PERMANENT_DECAY_RATE**days_ago)
    else:
        return record["importance"] * (AUTO_DECAY_RATE**days_ago)


def get_milestone_context() -> str:
    if os.path.exists(MILESTONE_FILE):
        with open(MILESTONE_FILE, "r", encoding="utf-8") as f:
            all_stories = json.load(f)

            if not all_stories:
                return "我们刚开始认识。"

            now = datetime.now()

            for s in all_stories:
                s["current_weight"] = get_weight(s, now)

            top_weight = sorted(
                all_stories, key=lambda x: x["current_weight"], reverse=True
            )[:IMPORTANT_MEMORY_TOP_COUNT]

            sorted_by_date = sorted(
                all_stories, key=lambda x: x["date"], reverse=True
            )
            recent = []
            for s in sorted_by_date:
                if s not in top_weight and len(recent) < IMPORTANT_MEMORY_RECENT_COUNT:
                    recent.append(s)

            final_stories = top_weight + recent
            return "\n".join(
                [f"{s['date']}：{s['event']}" for s in final_stories]
            )

    return "我们刚开始认识。"
