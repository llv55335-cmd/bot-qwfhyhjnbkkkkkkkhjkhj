"""机器人主程序入口"""
from dotenv import load_dotenv
load_dotenv()

import asyncio
import lark_oapi as lark
from lark_oapi.ws import Client
from config import FEISHU_APP_ID, FEISHU_APP_SECRET
from ports.feishu import handle_message, handle_enter_event, daily_check_weekly_review

def main():
    loop = asyncio.get_event_loop()
    loop.create_task(daily_check_weekly_review())
    event_handler = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(handle_message) \
        .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(handle_enter_event) \
        .build()
    ws_client = Client(
        app_id=FEISHU_APP_ID,
        app_secret=FEISHU_APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.DEBUG,
    )
    print("🚀 已上线，正在等待...")
    ws_client.start()

if __name__ == "__main__":
    main()
