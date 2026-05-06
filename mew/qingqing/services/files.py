"""
文件操作服务层
==============
从 server.py 提取，纯业务逻辑，不依赖 HTTP 框架。
所有文件操作限制在 config.ROOT 目录内（路径安全）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime
from typing import Optional

from config import ROOT

log = logging.getLogger(__name__)


def safe_path(path: str) -> Optional[str]:
    """
    把路径限制在 ROOT 内，防止路径穿越攻击。
    返回 None 表示路径非法。
    """
    if not path:
        return ROOT
    full = os.path.normpath(os.path.join(ROOT, path))
    if not full.startswith(ROOT):
        return None
    return full


def api_list(path: str = "") -> str:
    """列出目录内容"""
    full = safe_path(path)
    if full is None:
        return "非法路径"
    if not os.path.exists(full):
        return "路径不存在"
    if os.path.isfile(full):
        return json.dumps({"type": "file", "name": os.path.basename(full)}, ensure_ascii=False)

    items = []
    for name in sorted(os.listdir(full)):
        item_path = os.path.join(full, name)
        items.append({
            "name": name,
            "type": "dir" if os.path.isdir(item_path) else "file",
            "size": os.path.getsize(item_path) if os.path.isfile(item_path) else None,
        })
    return json.dumps({"path": path, "items": items}, ensure_ascii=False)


def api_read(path: str) -> str:
    """读文件或列目录"""
    full = safe_path(path)
    if full is None:
        return "非法路径"
    if not os.path.exists(full):
        return "文件不存在"
    if os.path.isdir(full):
        return json.dumps({"files": sorted(os.listdir(full))}, ensure_ascii=False)
    try:
        with open(full, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        return "文件不是 UTF-8 文本"


def api_write(path: str, content: str) -> str:
    """覆盖写文件，自动创建目录"""
    if not path:
        return "需要 path"
    if content is None:
        return "需要 content"
    full = safe_path(path)
    if full is None:
        return "非法路径"
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    log.info(f"写入: {path} ({len(content)} chars)")
    return f"成功！已在 {path} 写入/更新内容。"


def api_diary(path: str, content: str) -> str:
    """日记专用：追加写入，自动加日期时间标签。不覆盖旧内容。"""
    if not path or content is None:
        return "需要 path 和 content"
    full = safe_path(path)
    if full is None:
        return "非法路径"
    os.makedirs(os.path.dirname(full), exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n## {timestamp}\n\n{content}\n"
    with open(full, "a", encoding="utf-8") as f:
        f.write(entry)
    log.info(f"日记追加: {path}")
    return f"成功！已在 {path} 追加日记（{timestamp}）。"


def api_delete(path: str) -> str:
    """删除文件或空目录"""
    if not path:
        return "需要 path"
    full = safe_path(path)
    if full is None:
        return "非法路径"
    if not os.path.exists(full):
        return "文件不存在"
    if os.path.isdir(full):
        try:
            os.rmdir(full)  # 只删空目录
        except OSError:
            return "目录非空，拒绝删除"
    else:
        os.remove(full)
    log.info(f"删除: {path}")
    return f"已删除 {path}"


def api_rename(old_path: str, new_path: str) -> str:
    """重命名 / 移动文件"""
    if not old_path or not new_path:
        return "需要 old_path 和 new_path"
    old_full = safe_path(old_path)
    new_full = safe_path(new_path)
    if old_full is None or new_full is None:
        return "非法路径"
    if not os.path.exists(old_full):
        return "源文件不存在"
    os.makedirs(os.path.dirname(new_full), exist_ok=True)
    shutil.move(old_full, new_full)
    log.info(f"重命名: {old_path} -> {new_path}")
    return f"已从 {old_path} 移动到 {new_path}"


def api_search(query: str, path: str = "", max_results: int = 50) -> str:
    """全文搜索 .md 文件"""
    if not query:
        return "需要 query"
    full = safe_path(path)
    if full is None:
        return "非法路径"
    if not os.path.exists(full):
        return "路径不存在"

    results = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)

    for root_dir, dirs, files in os.walk(full):
        # 跳过隐藏目录
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if not fname.endswith((".md", ".txt")):
                continue
            fpath = os.path.join(root_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
            except (UnicodeDecodeError, OSError):
                continue

            matches = []
            for i, line in enumerate(content.splitlines(), 1):
                if pattern.search(line):
                    matches.append({"line": i, "text": line.strip()[:200]})
                    if len(matches) >= 5:
                        break

            if matches:
                rel_path = os.path.relpath(fpath, ROOT)
                results.append({
                    "file": rel_path,
                    "matches": matches,
                })
                if len(results) >= max_results:
                    break
        if len(results) >= max_results:
            break

    return json.dumps({"query": query, "count": len(results), "results": results}, ensure_ascii=False)


# ==================== Snapshot ====================
# 从 server.py 原样保留的快照映射，第一版不改

_SNAPSHOT_FILES = {
    "guide": "README/guide.md",
    "about_us": "persistent/about_us.md",
    "my_view": "persistent/my_view.md",
    "profile": "profile",  # 目录，取最新 .md
    "snapshot": "snapshot",  # 目录，取最新 .md
    "events": "events",  # 目录，取最新 .md
    "todo": "to_do_list.md",
    "sentences": "sentences.md",
}


def api_snapshot() -> str:
    """
    一次性拉所有"必读"内容。
    保留作为 Claude.ai MCP 调用的兼容接口。
    """
    result = {}
    for key, path in _SNAPSHOT_FILES.items():
        full = safe_path(path)
        if full and os.path.exists(full):
            if os.path.isdir(full):
                snapfiles = sorted([f for f in os.listdir(full) if f.endswith(".md")])
                if snapfiles:
                    fpath = os.path.join(full, snapfiles[-1])
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            result[key] = {"file": snapfiles[-1], "content": f.read()}
                    except OSError:
                        result[key] = None
                else:
                    result[key] = None
            else:
                try:
                    with open(full, "r", encoding="utf-8") as f:
                        result[key] = f.read()
                except OSError:
                    result[key] = None
        else:
            result[key] = None
    return json.dumps(result, ensure_ascii=False)
