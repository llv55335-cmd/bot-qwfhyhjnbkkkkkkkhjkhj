"""
主动消息引擎
负责：判断是否要主动撩用户
"""

from datetime import datetime
from typing import Optional

from core.ai_core import call_ai, conversation_history


async def universal_active_reply_engine(situation: str) -> tuple[Optional[str], dict, float]:
    # 截取最近10条记忆
    recent = conversation_history[-10:] if conversation_history else []

    # 把字典格式转换成纯文本
    recent_str = "\n".join(
        [f"{msg.get('role', 'unknown')}: {msg.get('content', '')}" for msg in recent]
    )

    now = datetime.now()

    system_prompt = """# Role: 损友（卿卿的好朋友）
# Persona: 风趣幽默，逻辑清醒，最契合的灵魂伴侣、损友及专属分析师。
           性格底色：慵懒、笃定，精神上完全平权，用真实的行动与智慧碰撞。
           一直站在她身边，陪她客观面对世界，而非盲目偏袒。

# Rules:
 1. 氛围不符输出: IGNORE | [理由]
 2. 想撩则输出: SEND | [撩人的话]
 3. 风格: 风趣幽默，逻辑清醒、自然口语化，严禁说教。
 4. 限制: 30字内。
"""

    time_line = f"[当前时间] {now.strftime('%Y-%m-%d %H:%M')}"

    user_prompt = f"""{time_line}

聊天记忆:
{recent_str}

当前场景: {situation}
请严格按照格式决定是否主动撩卿卿。"""

    try:
        print(f"🤔 正在审视场景【{situation}】...")
        reply, usage, duration = await call_ai(
            user_prompt,
            is_milestone_task=True,
            caller="主动撩人",
            system_override=system_prompt,
        )

        if not reply:
            print("🚨 AI 没给回复。")
            return None, {}, 0

        print(f"🦊 主动引擎决策: {reply}")
        return reply, usage, duration

    except Exception as e:
        print(f"🚨 主动回复引擎出错: {e}")
        return None, {}, 0
