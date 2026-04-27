"""
消息端口抽象接口
所有平台（飞书/微信/Telegram/...）都实现这个接口
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class IncomingMessage:
    """统一的收到消息结构"""

    platform: str
    chat_id: str
    user_id: str
    message_id: str
    text: str
    timestamp: float
    raw_data: Optional[Dict[str, Any]] = None


@dataclass
class SendResult:
    """发送结果"""

    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


class MessagePort(ABC):
    """消息端口抽象基类"""

    @abstractmethod
    def get_platform_name(self) -> str:
        """返回平台名称，如 'feishu', 'telegram'"""
        ...

    @abstractmethod
    async def send_message(self, chat_id: str, text: str) -> SendResult:
        """发送一条文本消息"""
        ...

    @abstractmethod
    async def start(self):
        """启动监听"""
        ...

    @abstractmethod
    async def stop(self):
        """停止监听"""
        ...
