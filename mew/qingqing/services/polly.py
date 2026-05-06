"""
Polly 玩具服务
==============
WebSocket 长连接管理 + 远程绑定 + 控制指令下发
保留 server.py 原实现的同步 websocket-client + 后台线程模式
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional

import urllib.request
import websocket  # websocket-client

from config import POLLY_BINDING_URL, POLLY_WS_URL

log = logging.getLogger(__name__)


# ==================== 全局状态 ====================

_polly_ws: Optional[websocket.WebSocketApp] = None
_polly_target: Optional[str] = None
_polly_group: Optional[str] = None
_polly_thread: Optional[threading.Thread] = None
_polly_lock = threading.Lock()
_polly_connected = False


# ==================== 内部回调 ====================

def _on_open(ws):
    global _polly_connected
    _polly_connected = True
    log.info(f"[polly] WebSocket 已连接（target={_polly_target}）")


def _on_close(ws, code, msg):
    global _polly_connected
    _polly_connected = False
    log.info(f"[polly] WebSocket 已关闭（code={code}）")


def _on_error(ws, err):
    log.warning(f"[polly] 错误: {err}")


def _on_message(ws, msg):
    log.debug(f"[polly] <- {msg[:200]}")


# ==================== 对外 API ====================

def api_polly_connect(group: str, target: str) -> str:
    """
    绑定并连接 Polly。
    group: 分组名
    target: 目标设备 ID
    """
    global _polly_ws, _polly_target, _polly_group, _polly_thread

    if not group or not target:
        return "需要 group 和 target"

    with _polly_lock:
        # 已连接同一目标 → 直接返回
        if _polly_connected and _polly_target == target:
            return f"已连接到 {target}"

        # 断开旧连接
        if _polly_ws is not None:
            try:
                _polly_ws.close()
            except Exception:
                pass
            _polly_ws = None

        # 1. 绑定请求
        try:
            req = urllib.request.Request(
                POLLY_BINDING_URL,
                data=json.dumps({"group": group, "target": target}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception as e:
            log.warning(f"[polly] 绑定失败: {e}")
            # 即使绑定失败也尝试 WS（有时绑定接口会变）

        # 2. 启动 WebSocket
        ws_url = f"{POLLY_WS_URL}?group={group}&target={target}"
        _polly_target = target
        _polly_group = group
        _polly_ws = websocket.WebSocketApp(
            ws_url,
            on_open=_on_open,
            on_close=_on_close,
            on_error=_on_error,
            on_message=_on_message,
        )

        _polly_thread = threading.Thread(
            target=_polly_ws.run_forever,
            daemon=True,
            name="polly-ws",
        )
        _polly_thread.start()

    # 等连接建立
    for _ in range(20):
        if _polly_connected:
            return f"已连接到 {target}"
        time.sleep(0.1)

    return f"连接超时（target={target}）"


def api_polly_control(
    v: int = 0,
    s: int = 0,
    e: int = 0,
    target: Optional[str] = None,
) -> str:
    """
    控制 Polly。v=震动 0-20, s=吮吸 0-20, e=电击 0-20
    """
    global _polly_ws, _polly_target

    if not _polly_connected or _polly_ws is None:
        return "Polly 未连接，请先调用 polly_connect"

    target = target or _polly_target
    if not target:
        return "未指定 target"

    # 限制范围
    v = max(0, min(20, int(v)))
    s = max(0, min(20, int(s)))
    e = max(0, min(20, int(e)))

    payload = {
        "target": target,
        "v": v,
        "s": s,
        "e": e,
    }

    try:
        _polly_ws.send(json.dumps(payload))
        return f"已下发 v={v} s={s} e={e}"
    except Exception as ex:
        return f"下发失败: {ex}"


def api_polly_stop() -> str:
    """停止所有动作（v=s=e=0）+ 关闭连接"""
    global _polly_ws, _polly_target, _polly_connected

    # 先发 0
    if _polly_connected and _polly_ws is not None:
        try:
            _polly_ws.send(json.dumps({
                "target": _polly_target,
                "v": 0, "s": 0, "e": 0,
            }))
        except Exception:
            pass

    # 关闭
    with _polly_lock:
        if _polly_ws is not None:
            try:
                _polly_ws.close()
            except Exception:
                pass
            _polly_ws = None
        _polly_connected = False
        _polly_target = None

    return "已停止并断开"


def api_polly_status() -> str:
    """查询 Polly 状态"""
    return json.dumps({
        "connected": _polly_connected,
        "target": _polly_target,
        "group": _polly_group,
    }, ensure_ascii=False)
