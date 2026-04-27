"""简化日志 - 后续按需扩展"""
import logging, os
from config import LOG_LEVEL, LOG_FILE

logger = logging.getLogger("ai_system")
logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
_fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
logger.addHandler(_ch)

def info(msg, **kw): logger.info(msg)
def error(msg, **kw): logger.error(msg)
def debug(msg, **kw): logger.debug(msg)
def warning(msg, **kw): logger.warning(msg)
