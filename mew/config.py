"""
全局配置模块
集中管理所有配置项，优先从环境变量读取
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv("DATA_DIR", BASE_DIR)


def _data_path(filename: str) -> str:
    return os.path.join(DATA_DIR, filename)


# ==================== 飞书 ====================

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

LAST_GREET_FILE = os.getenv("LAST_GREET_FILE", "")
FEISHU_CALENDAR_ID = os.getenv("FEISHU_CALENDAR_ID", "")

# ==================== AI 模型 ====================

KEY = os.getenv("KEY", "")
MODEL_NAME = os.getenv("MODEL", "")
API_URL = os.getenv("API_URL", "")

# 系统任务用的模型（大事记/周总结/主动消息，可用便宜模型）
SYSTEM_MODEL = os.getenv("SYSTEM_MODEL", MODEL_NAME)
SYSTEM_API_URL = os.getenv("SYSTEM_API_URL", API_URL)
SYSTEM_KEY = os.getenv("SYSTEM_KEY", KEY)

# ==================== 记忆系统 ====================

MEMORY_FILE = os.getenv("MEMORY_FILE", _data_path("short_term_memory.json"))
MILESTONE_FILE = os.getenv("MILESTONE_FILE", _data_path("important_memories.json"))
LONG_TERM_MEMORY_FILE = os.getenv("LONG_TERM_MEMORY_FILE", _data_path("long_term_memory.json"))

SHORT_TERM_MEMORY_SIZE = 20

# 记忆衰减
PERMANENT_DECAY_RATE = 0.99
AUTO_DECAY_RATE = 0.9
IMPORTANT_MEMORY_TOP_COUNT = 20
IMPORTANT_MEMORY_RECENT_COUNT = 20

# ==================== AI 成长 ====================

AI_EVOLUTION_FILE = os.getenv("AI_EVOLUTION_FILE", _data_path("ai_evolution.json"))
AI_EVOLUTION_KEEP_COUNT = 50
AI_REVIEW_INTERVAL = 10

# ==================== 时间 ====================

SILENT_CHECK_HOURS = 3.5
STAY_CHECK_SECONDS = 45
MORNING_START_HOUR = 8
MORNING_END_HOUR = 10
NIGHT_START_HOUR = 23
SLEEP_START_HOUR = 23
SLEEP_END_HOUR = 8
MIN_REMIND_DELAY_SECONDS = 1

# ==================== 消息聚合 ====================

MESSAGE_AGGREGATION_SECONDS = 15

# ==================== Prompt / Rules ====================

PROMPT_FILE = os.getenv("PROMPT_FILE", _data_path("prompt.json"))
RULES_FILE = os.getenv("RULES_FILE", _data_path("rules.json"))

USER_PROFILE = os.getenv("USER_PROFILE",_data_path("user.json"))

# ==================== Token / 日志 ====================

TOKEN_LOG_FILE = os.getenv("TOKEN_LOG_FILE", _data_path("token_usage.json"))
FULL_HISTORY_FILE = os.getenv("FULL_HISTORY_FILE", "full_history.txt")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "ai_system.log")

# ==================== 以下几行加到 config.py 末尾 ====================

# Trilium ETAPI
TRILIUM_API_TOKEN = os.getenv("TRILIUM_API_TOKEN", "")
TRILIUM_BASE_URL = os.getenv("TRILIUM_BASE_URL", "http://localhost:8080/etapi")
# 周总结放在 Trilium 哪个父节点下，填笔记 ID，留空则放 root
TRILIUM_WEEKLY_PARENT_ID = os.getenv("TRILIUM_WEEKLY_PARENT_ID", "root")

# ==================== xiaowo-release 集成 ====================

# xiaowo-release API 地址（通过 ngrok 暴露）
XIAOWO_API_URL = os.getenv("XIAOWO_API_URL", "http://localhost:3456")

# 功能开关
XIAOWO_ENABLE_MUSIC = os.getenv("XIAOWO_ENABLE_MUSIC", "true") == "true"
XIAOWO_ENABLE_TRAVEL = os.getenv("XIAOWO_ENABLE_TRAVEL", "true") == "true"
XIAOWO_ENABLE_CODE_ANALYSIS = os.getenv("XIAOWO_ENABLE_CODE_ANALYSIS", "true") == "true"

# xiaowo-release 专用 API 密钥（如果与主项目不同）
XIAOWO_LLM_API_KEY = os.getenv("XIAOWO_LLM_API_KEY", "")
XIAOWO_LLM_BASE_URL = os.getenv("XIAOWO_LLM_BASE_URL", "")
XIAOWO_LLM_MODEL = os.getenv("XIAOWO_LLM_MODEL", "")

# 代码分析缓存时间（秒）
CODE_ANALYSIS_CACHE_TTL = int(os.getenv("CODE_ANALYSIS_CACHE_TTL", "3600"))

# ==================== API 探索安全配置 ====================

# 允许访问的域名白名单（逗号分隔，支持通配符 *.example.com）
ALLOWED_DOMAINS = os.getenv("ALLOWED_DOMAINS", "*.de5.net,localhost,127.0.0.1,*.ngrok.io").split(",")

# 最大响应大小（字节），防止下载过大文件
MAX_RESPONSE_SIZE = int(os.getenv("MAX_RESPONSE_SIZE", "10485760"))  # 10MB

# 默认超时时间（秒）
API_EXPLORE_TIMEOUT = float(os.getenv("API_EXPLORE_TIMEOUT", "30.0"))

# 最大重试次数
API_EXPLORE_MAX_RETRIES = int(os.getenv("API_EXPLORE_MAX_RETRIES", "3"))

# 最大探索深度
API_EXPLORE_MAX_DEPTH = int(os.getenv("API_EXPLORE_MAX_DEPTH", "2"))

# 是否启用ngrok特殊处理（更长的超时、更多重试）
API_EXPLORE_NGROK_ENABLED = os.getenv("API_EXPLORE_NGROK_ENABLED", "true") == "true"

# ngrok额外超时（秒）
NGROK_EXTRA_TIMEOUT = float(os.getenv("NGROK_EXTRA_TIMEOUT", "10.0"))

# ngrok额外重试次数
NGROK_EXTRA_RETRIES = int(os.getenv("NGROK_EXTRA_RETRIES", "2"))
