"""
飞书 bot 启动管理
================
lark-oapi 的 ws_client.start() 是同步阻塞的，要丢到独立线程跑。
本模块封装：
  · start_feishu_bot()：被 app.py lifespan 调用，启动 WS 长连接
  · stop_feishu_bot()：被 app.py 关闭时调用，尽力关闭

约束：
  · 飞书消息处理逻辑在 ports/feishu.py（沿用 mew/ports/feishu.py）
  · 本模块只做"启停"封装，不动消息处理逻辑
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

log = logging.getLogger(__name__)


# ==================== 状态 ====================

_ws_client = None
_ws_future: Optional[asyncio.Future] = None


# ==================== 启动 ====================

async def start_feishu_bot() -> None:
    """
    启动飞书 bot：
      1. 恢复 pending 日程
      2. 启动每日维护任务
      3. 启动 WS 长连接（独立线程）
    """
    global _ws_client, _ws_future

    # 1. 恢复 pending 日程（如果模块就绪）
    try:
        from tools.schedule_manager import restore_all_pending
        restore_all_pending()
        log.info("[feishu_runner] 已恢复 pending 日程")
    except ImportError:
        log.debug("[feishu_runner] schedule_manager 未就绪，跳过日程恢复")
    except Exception as e:
        log.warning(f"[feishu_runner] 恢复日程失败（可忽略）: {e}")

    # 2. 启动每日维护任务（如果模块就绪）
    try:
        from ports.feishu import daily_check_weekly_review
        asyncio.create_task(daily_check_weekly_review())
        log.info("[feishu_runner] 每日维护任务已启动")
    except (ImportError, AttributeError) as e:
        log.debug(f"[feishu_runner] 每日维护任务未就绪: {e}")
    except Exception as e:
        log.warning(f"[feishu_runner] 启动每日维护任务失败: {e}")

    # 3. 启动 WS 长连接
    try:
        from ports.feishu import build_ws_client
        _ws_client = build_ws_client()
    except (ImportError, AttributeError) as e:
        log.warning(f"[feishu_runner] ports.feishu.build_ws_client 不可用: {e}")
        log.warning("[feishu_runner] 飞书 WS 未启动，HTTP 部分仍可用")
        return

    loop = asyncio.get_event_loop()
    _ws_future = loop.run_in_executor(None, _ws_client.start)
    log.info("[feishu_runner] 飞书 WS 已在独立线程启动")


# ==================== 关闭 ====================

async def stop_feishu_bot() -> None:
    """关闭飞书 bot"""
    global _ws_client, _ws_future

    if _ws_client is not None:
        try:
            # lark-oapi 没有标准的 stop() 方法，尝试常见的
            for method_name in ("stop", "close", "shutdown"):
                if hasattr(_ws_client, method_name):
                    method = getattr(_ws_client, method_name)
                    if asyncio.iscoroutinefunction(method):
                        await method()
                    else:
                        method()
                    log.info(f"[feishu_runner] 已调用 ws_client.{method_name}()")
                    break
        except Exception as e:
            log.warning(f"[feishu_runner] 关闭 WS 出错: {e}")

    if _ws_future is not None:
        try:
            _ws_future.cancel()
        except Exception:
            pass

    _ws_client = None
    _ws_future = None
    log.info("[feishu_runner] 飞书 bot 已关闭")
