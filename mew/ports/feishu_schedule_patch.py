# ==================== feishu.py 改动说明 ====================

# ===== 改动1：顶部import加 =====
# from tools.schedule_manager import update_last_active


# ===== 改动2：process_and_reply 最开头加一行 =====
# 在 print(f"🦊 思考用户消息...") 那行前面加：
#
# update_last_active(chat_id)


# ===== 改动3：加 handle_schedule_directive_if_any 函数 =====
# schedule_manager.py 里调用了这个函数，需要在 feishu.py 里定义：

async def handle_schedule_directive_if_any(chat_id: str, directive: str):
    from tools.schedule_manager import handle_schedule_directive
    await handle_schedule_directive(chat_id, directive)
