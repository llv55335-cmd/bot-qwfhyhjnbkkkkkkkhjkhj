"""
AI 周总结模块
负责：每周回顾对话，生成成长总结
"""

import os
import json
from datetime import datetime

from config import AI_EVOLUTION_FILE
from core.ai_core import call_ai


def _should_run_weekly_review() -> bool:
    if not os.path.exists(AI_EVOLUTION_FILE):
        return True

    with open(AI_EVOLUTION_FILE, "r", encoding="utf-8") as f:
        try:
            records = json.load(f)
        except Exception:
            return True

    if not records:
        return True

    last_date = records[-1].get("date", "")
    try:
        last_dt = datetime.strptime(last_date, "%Y-%m-%d")
        days_since = (datetime.now() - last_dt).days
        return days_since >= 7
    except Exception:
        return True


async def weekly_review(conversation_history):
    if not _should_run_weekly_review():
        print("📅 本周已做过总结，跳过")
        return

    recent = conversation_history[-40:]
    if len(recent) < 10:
        print("📅 对话太少，跳过周总结")
        return

    review_prompt = f"""
    回顾最近一周的对话：
    {recent}

    请做一份简短的周总结（100字内）：
    1. 这周卿卿的状态怎么样？
    2. 你和她之间有什么变化？
    3. 你想调整自己的地方？

    严格只输出总结内容，100字以内。
    如果没什么值得总结的，严格只输出：IGNORE
    """

    result_tuple = await call_ai(
        review_prompt, is_milestone_task=True, caller="周总结"
    )
    result = result_tuple[0] if result_tuple else None

    if result and "IGNORE" not in result:
        records = []
        if os.path.exists(AI_EVOLUTION_FILE):
            with open(AI_EVOLUTION_FILE, "r", encoding="utf-8") as f:
                try:
                    records = json.load(f)
                except Exception:
                    records = []

        records.append(
            {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "type": "weekly",
                "summary": result,
            }
        )

        with open(AI_EVOLUTION_FILE, "w", encoding="utf-8") as f:
            json.dump(records[-50:], f, ensure_ascii=False, indent=2)

        print(f"📅 周总结完成：{result[:50]}...")


def get_ai_evolution_context() -> str:
    if os.path.exists(AI_EVOLUTION_FILE):
        with open(AI_EVOLUTION_FILE, "r", encoding="utf-8") as f:
            try:
                records = json.load(f)
                return "\n".join(
                    [
                        f"{r['date']}：{r.get('summary', r.get('decision', ''))}"
                        for r in records[-5:]
                    ]
                )
            except Exception:
                pass
    return ""
