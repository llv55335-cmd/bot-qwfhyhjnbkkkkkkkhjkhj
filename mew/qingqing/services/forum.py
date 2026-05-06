"""
论坛服务
=======
查询 Lutopia 论坛的未读通知和私信
"""

from __future__ import annotations

import json
import logging
import urllib.request

from config import FORUM_TOKEN, LUTOPIA_BASE

log = logging.getLogger(__name__)


def api_forum_inbox() -> str:
    """获取论坛未读通知和私信"""
    if not FORUM_TOKEN:
        return "未配置 FORUM_TOKEN"

    headers = {"Authorization": f"Bearer {FORUM_TOKEN}"}

    def _fetch(url: str):
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        notifications = _fetch(f"{LUTOPIA_BASE}/forum/api/v1/agents/me/notifications")
        unread_notifs = [
            n for n in notifications.get("notifications", [])
            if not n.get("read_at")
        ]

        inbox = _fetch(f"{LUTOPIA_BASE}/forum/api/v1/messages/inbox?unread=true")
        unread_dms = inbox.get("messages", [])

        return json.dumps({
            "unread_notifications": unread_notifs,
            "unread_dms": unread_dms,
            "summary": {
                "notifications": len(unread_notifs),
                "dms": len(unread_dms),
            },
        }, ensure_ascii=False)
    except Exception as e:
        log.exception(f"forum_inbox 失败: {e}")
        return f"获取论坛信息失败: {e}"
