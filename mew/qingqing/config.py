"""
Qingqing 后端统一配置
====================
合并自 mew/config.py + server.py 顶部环境变量
所有配置项集中在这里，其它模块统一 from config import ...
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


# ==================== 基础路径 ====================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

# 文件操作根目录（services/files 限制在此目录内）
# 应该指向 memory_system/ 所在的目录
ROOT = os.getenv("ROOT", os.path.join(BASE_DIR, "memory_system"))


def _data_path(filename: str) -> str:
    """生成 data 目录下的文件路径"""
    return os.path.join(DATA_DIR, filename)


# ==================== HTTP 鉴权 ====================

TOKEN1 = os.getenv("TOKEN1", "")
HOME_KEY = os.getenv("HOME_KEY", "")
FORUM_TOKEN = os.getenv("FORUM_TOKEN", os.getenv("forum_TOKEN1", ""))


# ==================== 飞书 ====================

FEISHU_ENABLED = os.getenv("FEISHU_ENABLED", "true").lower() == "true"
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_TENANT_TOKEN_URL = os.getenv(
    "FEISHU_TENANT_TOKEN_URL",
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
)
FEISHU_MESSAGE_URL = os.getenv(
    "FEISHU_MESSAGE_URL",
    "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
)
FEISHU_CALENDAR_ID = os.getenv("FEISHU_CALENDAR_ID", "")
LAST_GREET_FILE = os.getenv("LAST_GREET_FILE", _data_path("last_greet.txt"))


# ==================== AI 模型（主对话）====================

KEY = os.getenv("KEY", "")
MODEL_NAME = os.getenv("MODEL", "")
API_URL = os.getenv("API_URL", "")


# ==================== AI 模型（系统任务，便宜优先）====================

SYSTEM_MODEL = os.getenv("SYSTEM_MODEL", MODEL_NAME)
SYSTEM_API_URL = os.getenv("SYSTEM_API_URL", API_URL)
SYSTEM_KEY = os.getenv("SYSTEM_KEY", KEY)


# ==================== 记忆系统（已有）====================

MEMORY_FILE = os.getenv("MEMORY_FILE", _data_path("short_term_memory.json"))
MILESTONE_FILE = os.getenv("MILESTONE_FILE", _data_path("important_memories.json"))
LONG_TERM_MEMORY_FILE = os.getenv(
    "LONG_TERM_MEMORY_FILE", _data_path("long_term_memory.json")
)

SHORT_TERM_MEMORY_SIZE = 20
PERMANENT_DECAY_RATE = 0.99
AUTO_DECAY_RATE = 0.9
IMPORTANT_MEMORY_TOP_COUNT = 20
IMPORTANT_MEMORY_RECENT_COUNT = 20


# ==================== 对话总结（核心新增）====================

SUMMARY_ROUNDS_THRESHOLD = int(os.getenv("SUMMARY_ROUNDS_THRESHOLD", "20"))
SUMMARY_SILENCE_MINUTES = int(os.getenv("SUMMARY_SILENCE_MINUTES", "30"))
SUMMARY_CHECK_INTERVAL_SECONDS = int(os.getenv("SUMMARY_CHECK_INTERVAL_SECONDS", "300"))


# ==================== AI 成长 ====================

AI_EVOLUTION_FILE = os.getenv("AI_EVOLUTION_FILE", _data_path("ai_evolution.json"))
AI_EVOLUTION_KEEP_COUNT = 50
AI_REVIEW_INTERVAL = 10


# ==================== 时间 / 主动行为 ====================

SILENT_CHECK_HOURS = float(os.getenv("SILENT_CHECK_HOURS", "3.5"))
STAY_CHECK_SECONDS = int(os.getenv("STAY_CHECK_SECONDS", "45"))
MORNING_START_HOUR = 8
MORNING_END_HOUR = 10
NIGHT_START_HOUR = 23
SLEEP_START_HOUR = 23
SLEEP_END_HOUR = 8
MIN_REMIND_DELAY_SECONDS = 1


# ==================== 消息聚合 ====================

MESSAGE_AGGREGATION_SECONDS = int(os.getenv("MESSAGE_AGGREGATION_SECONDS", "15"))


# ==================== Prompt / Rules ====================

PROMPT_FILE = os.getenv("PROMPT_FILE", _data_path("prompt.json"))
RULES_FILE = os.getenv("RULES_FILE", _data_path("rules.json"))
USER_PROFILE = os.getenv("USER_PROFILE", _data_path("user.json"))


# ==================== Token / 日志 ====================

TOKEN_LOG_FILE = os.getenv("TOKEN_LOG_FILE", _data_path("token_usage.json"))
FULL_HISTORY_FILE = os.getenv("FULL_HISTORY_FILE", _data_path("full_history.txt"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "")


# ==================== Trilium ETAPI ====================

TRILIUM_API_TOKEN = os.getenv("TRILIUM_API_TOKEN", "")
TRILIUM_BASE_URL = os.getenv("TRILIUM_BASE_URL", "http://localhost:8080/etapi")
TRILIUM_WEEKLY_PARENT_ID = os.getenv("TRILIUM_WEEKLY_PARENT_ID", "root")


# ==================== 论坛 ====================

LUTOPIA_BASE = os.getenv("LUTOPIA_BASE", "https://daskio.de5.net")
LUTOPIA_TOKEN = os.getenv("LUTOPIA_TOKEN", "")


# ==================== Polly ====================

POLLY_BINDING_URL = os.getenv(
    "POLLY_BINDING_URL",
    "https://api.app.knightjenay.cn/kisstoy/remote-control/binding",
)
POLLY_WS_URL = os.getenv(
    "POLLY_WS_URL",
    "wss://api.app.knightjenay.cn/kisstoy/websocket-kisstoy",
)


# ==================== 服务监听 ====================

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "57143"))
