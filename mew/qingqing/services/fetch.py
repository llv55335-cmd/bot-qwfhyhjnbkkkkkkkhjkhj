"""
网页抓取服务
==========
从 server.py 提取，自动识别 JSON / HTML，trafilatura 提取正文，5 分钟内存缓存。
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

import trafilatura

log = logging.getLogger(__name__)


# ==================== 缓存 ====================

_FETCH_CACHE: Dict[tuple, tuple] = {}  # key=(url,max_chars,with_links,raw), value=(ts, response)
_FETCH_CACHE_TTL = 300  # 5 分钟


# ==================== UA 预设 ====================

_UA_PRESETS = {
    "desktop": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "mobile": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "bot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
}


# ==================== 主函数 ====================

def api_fetch_url(
    url: str,
    max_chars: int = 10000,
    with_links: bool = False,
    raw: bool = False,
    timeout: int = 20,
    no_cache: bool = False,
    ua: str = "desktop",
) -> str:
    """
    抓网页：JSON > trafilatura 正文 > 原始文本
    """
    if not url or not url.startswith(("http://", "https://")):
        return "URL 必须以 http:// 或 https:// 开头"

    # 限制 timeout 范围
    timeout = max(3, min(60, timeout))

    cache_key = (url, max_chars, with_links, raw)
    now = time.time()

    # 缓存查询
    if not no_cache and cache_key in _FETCH_CACHE:
        ts, cached = _FETCH_CACHE[cache_key]
        if now - ts < _FETCH_CACHE_TTL:
            log.debug(f"[fetch_url] cache hit: {url}")
            return cached

    user_agent = _UA_PRESETS.get(ua, _UA_PRESETS["desktop"])
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()

            raw_bytes = resp.read()
            try:
                text = raw_bytes.decode(charset, errors="replace")
            except (LookupError, TypeError):
                text = raw_bytes.decode("utf-8", errors="replace")

            final_url = resp.geturl()

    except urllib.error.HTTPError as e:
        return f"HTTP 错误 {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return f"网络错误: {e.reason}"
    except TimeoutError:
        return f"请求超时（{timeout}s）"
    except Exception as e:
        return f"抓取失败: {e}"

    # 处理：raw 模式直接返回
    if raw:
        result = text[:max_chars] if len(text) > max_chars else text
        result = json.dumps({"url": final_url, "content": result}, ensure_ascii=False)
        if not no_cache:
            _FETCH_CACHE[cache_key] = (now, result)
        return result

    # JSON 内容：直接返回
    is_json = "application/json" in content_type or text.lstrip().startswith(("{", "["))
    if is_json:
        try:
            data = json.loads(text)
            result = json.dumps({"url": final_url, "type": "json", "data": data}, ensure_ascii=False)
            if len(result) > max_chars:
                result = result[:max_chars] + "...(截断)"
            if not no_cache:
                _FETCH_CACHE[cache_key] = (now, result)
            return result
        except json.JSONDecodeError:
            pass  # 当成 HTML 处理

    # HTML：用 trafilatura 提取正文
    extracted = trafilatura.extract(
        text,
        include_links=with_links,
        include_comments=False,
        favor_recall=True,
    )

    if not extracted:
        # 兜底：返回截断的原始文本
        extracted = text[:max_chars]

    if len(extracted) > max_chars:
        extracted = extracted[:max_chars] + "...(截断)"

    result = json.dumps({"url": final_url, "type": "html", "content": extracted}, ensure_ascii=False)

    if not no_cache:
        _FETCH_CACHE[cache_key] = (now, result)

    return result


def clear_fetch_cache() -> str:
    """清空 fetch 缓存"""
    count = len(_FETCH_CACHE)
    _FETCH_CACHE.clear()
    return f"已清空 {count} 条缓存"
