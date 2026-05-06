"""
Qingqing 后端统一入口
====================
合并 mew/ 飞书 AI 伴侣 + server.py HTTP 工具服务
单进程 FastAPI + Uvicorn，飞书 WS 作为 startup 后台 task

启动：
  python app.py
或：
  uvicorn app:app --host 0.0.0.0 --port 57143 --workers 1
"""

from __future__ import annotations

# ★ PyTorch DLL 路径修复（Python 装在盘根目录时的边界情况）
# Torch 用 os.path.join(sys.exec_prefix, "bin") 拼出 "D:bin" 而非 "D:\\bin"
# os.add_dll_directory("D:bin") 在 Windows 上报 WinError 87（参数错误）
import sys as _sys
if _sys.exec_prefix and len(_sys.exec_prefix) == 2 and _sys.exec_prefix[1] == ":":
    _sys.exec_prefix = _sys.exec_prefix + "\\"

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from config import (
    FEISHU_ENABLED,
    HOME_KEY,
    HOST,
    LOG_FILE,
    LOG_LEVEL,
    PORT,
    TOKEN1,
)

# 路由
from adapters import http_files, http_mcp, http_tools

# ==================== 日志配置 ====================

_log_handlers = [logging.StreamHandler()]
if LOG_FILE:
    os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)
    _log_handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_log_handlers,
)
log = logging.getLogger("qingqing")


# ==================== 生命周期 ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """startup 拉起后台服务，shutdown 优雅停止"""
    log.info("=" * 50)
    log.info("🚀 Qingqing 后端启动中...")
    log.info("=" * 50)

    # 1. 飞书 bot
    if FEISHU_ENABLED:
        try:
            from ports.feishu_runner import start_feishu_bot
            await start_feishu_bot()
            log.info("✅ 飞书 bot 已启动")
        except ImportError as e:
            log.warning(f"⚠️  飞书模块未就绪（{e}），跳过启动。HTTP 部分仍可用。")
        except Exception as e:
            log.exception(f"飞书 bot 启动失败: {e}")
    else:
        log.info("⏸️  飞书 bot 已禁用（FEISHU_ENABLED=false）")

    # 2. 对话总结后台任务（如果模块就绪）
    try:
        from core.conversation_summarizer import periodic_summary_check
        import asyncio
        app.state.summary_task = asyncio.create_task(periodic_summary_check())
        log.info("✅ 对话总结后台任务已启动")
    except ImportError:
        log.info("ℹ️  对话总结模块未就绪，跳过")
    except Exception as e:
        log.warning(f"对话总结任务启动失败: {e}")

    log.info("✨ 后端就绪")

    yield

    # ===== 关闭 =====
    log.info("🛑 关闭中...")
    if hasattr(app.state, "summary_task"):
        app.state.summary_task.cancel()

    if FEISHU_ENABLED:
        try:
            from ports.feishu_runner import stop_feishu_bot
            await stop_feishu_bot()
        except Exception as e:
            log.warning(f"飞书 bot 关闭时出错: {e}")

    # 关闭 Polly（如果连着）
    try:
        from services import polly as polly_svc
        polly_svc.api_polly_stop()
    except Exception:
        pass


# ==================== FastAPI 实例 ====================

app = FastAPI(
    title="Qingqing Backend",
    version="4.0.0",
    description="飞书 AI 伴侣 + 文件/网页/Polly/记忆 统一后端",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 防火墙 + 鉴权 ====================

MALICIOUS_EXACT = {
    "/phpinfo.php", "/info.php", "/php.php", "/i.php",
    "/test.php", "/p.php", "/debug.php",
}
MALICIOUS_PREFIXES = (
    "/wp-", "/wordpress", "/admin", "/.git", "/.env", "/cgi-bin",
)

# 公开路径白名单
PUBLIC_PATHS = {
    "/", "/health", "/sse", "/messages",
    "/favicon.ico", "/docs", "/openapi.json", "/redoc",
}


@app.middleware("http")
async def firewall_and_auth(request: Request, call_next):
    path_lower = request.url.path.lower()

    # 1. 防火墙
    if path_lower in MALICIOUS_EXACT or any(
        path_lower.startswith(p) for p in MALICIOUS_PREFIXES
    ):
        return PlainTextResponse("Not Found", status_code=404)

    # 2. Token 鉴权
    if path_lower not in PUBLIC_PATHS and not path_lower.startswith("/static"):
        if TOKEN1:
            token = (
                request.query_params.get("token")
                or request.headers.get("X-Token")
            )
            if token != TOKEN1:
                return PlainTextResponse("未授权", status_code=401)

    return await call_next(request)


# ==================== 路由注册 ====================

app.include_router(http_files.router, tags=["files"])
app.include_router(http_tools.router, tags=["tools"])
app.include_router(http_mcp.router, tags=["mcp"])


# ==================== 基础路由 ====================

@app.get("/", response_class=PlainTextResponse)
async def index(key: str = ""):
    """首页"""
    if HOME_KEY and key != HOME_KEY:
        return PlainTextResponse("Not Found", status_code=404)
    return _render_home()


@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "ok",
        "version": "4.0.0",
        "feishu_enabled": FEISHU_ENABLED,
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.exception(f"未处理异常 {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "path": str(request.url.path)},
    )


# ==================== 首页内容 ====================

def _render_home() -> str:
    return """
🏠 Qingqing Backend v4.0
📁 文件操作:    /list /read /write /delete /rename /diary /search /snapshot
🎲 工具:        /roll /fetch /forum/inbox
🌸 Polly:       /polly/connect /polly/control /polly/stop /polly/status
💝 私密空间:    /private/write /private/read /private/search /private/forget
🤖 MCP:         /sse /messages
📋 飞书:        WebSocket 自动连接（无 HTTP 入口）

文档: /docs（Swagger UI）
健康检查: /health
"""


# ==================== 入口 ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level=LOG_LEVEL.lower(),
        workers=1,  # 必须是 1，因为飞书 WS 和记忆系统有内存状态
    )