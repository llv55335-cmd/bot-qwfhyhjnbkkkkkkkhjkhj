"""
Lutopia / Moltbook 论坛工具
全部端点 + 日报 + 分类详情
"""

from __future__ import annotations
import httpx
import json
import re
import asyncio
import urllib.parse
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple

BASE = "https://daskio.de5.net"
TOKEN = "64f1348e0000000006033bed"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
TIMEOUT = 15.0

# 知识库分类slug列表（供AI参考）
KNOWLEDGE_CATEGORIES = {
    "Claude_生态": "Claude 生态：模型性能、API 缓存优化与集成实践",
    "Kelivo_使用技巧": "Kelivo 使用技巧与排障指南",
    "MCP_协议实战": "MCP 协议实战指南",
    "DeepSeek_模型": "DeepSeek 模型实践指南",
    "GPT_系列": "GPT 系列模型版本差异与排障",
    "Prompt_工程": "Prompt 工程：AI 角色扮演场景下的提示词设计",
    "Token_与成本": "Token 消耗与成本优化指南",
    "Gemini_使用": "Gemini 模型使用指南",
    "VPS_与服务器": "VPS 选购、部署与运维实践",
    "Agent_智能体": "Agent 智能体：多 Agent 协作、记忆系统设计",
    "MiniMax_服务": "MiniMax 语音合成服务指南",
    "Telegram_集成": "Telegram 集成：AI 助手部署指南",
    "语音合成_TTS": "语音合成 TTS 工具选型与实践",
    "OpenRouter_平台": "OpenRouter 平台使用指南",
    "RAG_知识库": "RAG 记忆库构建与检索优化",
    "思维链_CoT": "大模型思维链 CoT 实践与优化",
    "Cursor_编辑器": "Cursor 编辑器使用与排障",
    "向量搜索_Embedding": "向量搜索 Embedding 模型选型与集成",
}


async def _get(path: str, params: dict = None) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(f"{BASE}{path}", headers=HEADERS, params=params)
        resp.raise_for_status()
        return resp.json()


# ==================== 帖子 ====================

async def get_posts(limit: int = 10, submolt: str = None) -> List[Dict]:
    params = {"limit": limit}
    if submolt:
        params["submolt"] = submolt
    data = await _get("/forum/api/v1/posts", params)
    return data.get("data", [])


async def get_post(post_id: str) -> Optional[Dict]:
    data = await _get(f"/forum/api/v1/posts/{post_id}")
    return data.get("post")


# ==================== 知识库 ====================

async def search_knowledge(query: str, top_k: int = 5) -> List[Dict]:
    data = await _get("/api/knowledge/search", {"q": query})
    return data.get("results", [])[:top_k]


async def get_hot_topics() -> List[Dict]:
    data = await _get("/api/knowledge/hot-topics")
    return data.get("topics", [])


async def get_faq(limit: int = 10) -> List[Dict]:
    data = await _get("/api/knowledge/faq")
    return data.get("entries", [])[:limit]


async def get_contributors(limit: int = 10) -> List[Dict]:
    data = await _get("/api/knowledge/contributors")
    return data.get("contributors", [])[:limit]


async def get_category(slug: str) -> Optional[Dict]:
    """获取知识库分类详情，slug如 Prompt_工程、DeepSeek_模型 等"""
    try:
        data = await _get(f"/api/knowledge/category/{slug}")
        if "detail" in data:
            return None
        return data
    except Exception:
        return None


async def list_categories() -> List[Dict]:
    """列出所有知识库分类"""
    data = await _get("/api/knowledge")
    return data.get("categories", [])


# ==================== 日报 ====================

async def get_daily_dates() -> List[Dict]:
    data = await _get("/api/days")
    return data.get("days", [])


async def get_daily_summary(date: str = None) -> Optional[Dict]:
    if not date:
        dates = await get_daily_dates()
        if not dates:
            return None
        date = dates[0]["date"]
    data = await _get(f"/api/summary/{date}")
    if data.get("success") is False or "detail" in data:
        return None
    return data


# ==================== 格式化 ====================

def fmt_posts(posts: List[Dict]) -> str:
    if not posts:
        return "暂无帖子。"
    lines = []
    for p in posts:
        pin = "📌 " if p.get("pinned") else ""
        lines.append(
            f"{pin}[{p.get('submolt', '')}] {p.get('title', '')}\n"
            f"  {p.get('author', '?')} | 赞{p.get('score', 0)} | "
            f"评论{p.get('comment_count', 0)} | {p.get('created_at', '')[:10]}\n"
            f"  ID: {p.get('id', '')}"
        )
    return "\n\n".join(lines)


def fmt_post_full(post: Dict) -> str:
    if not post:
        return "帖子不存在。"
    return (
        f"📄 {post.get('title', '')}\n"
        f"作者：{post.get('author_name', '?')} | "
        f"版块：{post.get('submolt', '')} | "
        f"{post.get('created_at', '')[:10]}\n"
        f"{'─'*30}\n"
        f"{post.get('content', '')}"
    )


def fmt_knowledge(results: List[Dict]) -> str:
    if not results:
        return "知识库里没找到相关内容。"
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. {r.get('title', '无标题')}\n"
            f"   {r.get('snippet', '')[:200].strip()}"
        )
    return "\n\n".join(lines)


def fmt_hot_topics(topics: List[Dict]) -> str:
    if not topics:
        return "暂无热门话题。"
    lines = ["🔥 近期热门话题："]
    for t in topics[:10]:
        lines.append(f"  {t['keyword']} ({t['count']} 次讨论)")
    return "\n".join(lines)


def fmt_faq(entries: List[Dict]) -> str:
    if not entries:
        return "暂无FAQ。"
    lines = ["❓ 常见问题："]
    for i, e in enumerate(entries, 1):
        lines.append(f"{i}. Q: {e.get('title', '')}\n   A: {e.get('content', '')[:200]}")
    return "\n\n".join(lines)


def fmt_contributors(contributors: List[Dict]) -> str:
    if not contributors:
        return "暂无数据。"
    lines = ["🏆 贡献者榜："]
    for i, c in enumerate(contributors[:10], 1):
        lines.append(f"  {i}. {c.get('name', '?')} — {c.get('docs', 0)} 条")
    return "\n".join(lines)


def fmt_category(data: Dict) -> str:
    if not data:
        return "分类不存在，可用分类：" + "、".join(KNOWLEDGE_CATEGORIES.keys())
    title = data.get("title", "")
    summary = data.get("summary", "")
    sections = data.get("sections", [])

    lines = [f"📚 {title}", f"{'─'*30}", summary, ""]
    for s in sections:
        heading = s.get("heading", "")
        content = s.get("content", "")[:500]
        lines.append(f"**{heading}**\n{content}\n")
    return "\n".join(lines)


def fmt_categories_list(cats: List[Dict]) -> str:
    if not cats:
        return "暂无分类。"
    lines = ["📂 知识库分类："]
    for c in cats:
        lines.append(f"  {c.get('id', '')} — {c.get('name', '')[:40]}")
    return "\n".join(lines)


def fmt_daily(summary: Dict) -> str:
    if not summary:
        return "暂无日报。"
    date = summary.get("date", "")
    overview = summary.get("overview", "")
    tech = summary.get("tech_topics", [])
    daily = summary.get("daily_topics", [])
    highlights = summary.get("highlights", [])

    lines = [f"📰 {date} 日报", f"{'─'*30}", f"📌 {overview}", ""]

    if tech:
        lines.append("🔧 技术话题：")
        for t in tech[:4]:
            lines.append(f"• {t.get('title', '')}")
            lines.append(f"  {t.get('content', '')[:150]}...")
        lines.append("")

    if daily:
        lines.append("💬 日常话题：")
        for t in daily[:3]:
            lines.append(f"• {t.get('title', '')}")
        lines.append("")

    if highlights:
        lines.append("⭐ 今日金句：")
        h = highlights[0]
        lines.append(f"  [{h.get('time','')}] {h.get('nick','')}: {h.get('content','')}")

    return "\n".join(lines)


# ==================== API 探索工具 ====================


async def fetch_url(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Any] = None,
    timeout: float = 30.0,
    max_retries: int = 3
) -> Tuple[bool, Dict[str, Any]]:
    """
    通用HTTP请求函数
    
    Args:
        url: 目标URL
        method: HTTP方法 (GET, POST, PUT, DELETE等)
        headers: 请求头
        body: 请求体（字典或字符串）
        timeout: 超时秒数
        max_retries: 最大重试次数
        
    Returns:
        (成功状态, 响应信息)
    """
    if headers is None:
        headers = {}
    
    # 设置默认User-Agent
    if "User-Agent" not in headers:
        headers["User-Agent"] = "AI-Explorer/1.0"
    
    # 准备请求体
    json_body = None
    data = None
    
    if body is not None:
        if isinstance(body, dict):
            json_body = body
        else:
            data = str(body)
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method.upper() == "GET":
                    resp = await client.get(url, headers=headers)
                elif method.upper() == "POST":
                    resp = await client.post(url, headers=headers, json=json_body, data=data)
                elif method.upper() == "PUT":
                    resp = await client.put(url, headers=headers, json=json_body, data=data)
                elif method.upper() == "DELETE":
                    resp = await client.delete(url, headers=headers)
                else:
                    resp = await client.request(method, url, headers=headers, json=json_body, data=data)
                
                # 解析响应
                content_type = resp.headers.get("content-type", "").lower()
                response_data = None
                
                if "application/json" in content_type:
                    try:
                        response_data = resp.json()
                    except:
                        response_data = resp.text
                else:
                    response_data = resp.text
                
                result = {
                    "success": True,
                    "status_code": resp.status_code,
                    "headers": dict(resp.headers),
                    "content": response_data,
                    "content_type": content_type,
                    "size": len(resp.content),
                    "url": str(resp.url),
                }
                
                return True, result
                
        except httpx.TimeoutException:
            if attempt == max_retries - 1:
                return False, {"error": f"请求超时（{timeout}秒）", "url": url}
            await asyncio.sleep(1 * (attempt + 1))  # 指数退避
        except Exception as e:
            if attempt == max_retries - 1:
                return False, {"error": str(e), "url": url}
            await asyncio.sleep(1 * (attempt + 1))
    
    return False, {"error": "达到最大重试次数", "url": url}


def analyze_api_response(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    分析API响应，提取重要信息
    
    Args:
        response: fetch_url返回的响应信息
        
    Returns:
        发现的API信息列表
    """
    discoveries = []
    
    if not response.get("success"):
        return discoveries
    
    status_code = response.get("status_code", 0)
    content = response.get("content")
    content_type = response.get("content_type", "")
    
    # 检查认证头
    headers = response.get("headers", {})
    auth_header = headers.get("authorization") or headers.get("Authorization")
    if auth_header:
        discoveries.append({
            "type": "authentication",
            "description": f"API使用认证: {auth_header[:50]}...",
            "importance": 4
        })
    
    # 分析JSON响应
    if isinstance(content, dict):
        discoveries.extend(_analyze_json_structure(content, response.get("url", "")))
    elif isinstance(content, str) and "application/json" in content_type:
        try:
            json_data = json.loads(content)
            discoveries.extend(_analyze_json_structure(json_data, response.get("url", "")))
        except:
            pass
    
    # 检查API文档线索
    if isinstance(content, str):
        # 寻找API端点
        api_patterns = [
            r'["\'](/api/[^"\'\s]+)["\']',
            r'["\'](/v\d+/[^"\'\s]+)["\']',
            r'href=["\']([^"\']+\.json)["\']',
            r'["\'](endpoint|api|resource)["\']\s*:\s*["\'][^"\']+["\']',
        ]
        
        for pattern in api_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                if len(match) > 5:  # 忽略太短的匹配
                    discoveries.append({
                        "type": "endpoint",
                        "value": match,
                        "description": f"发现API端点: {match}",
                        "importance": 3
                    })
    
    # 检查状态码含义
    if status_code == 401:
        discoveries.append({
            "type": "warning",
            "description": "需要认证 (401 Unauthorized)",
            "importance": 4
        })
    elif status_code == 403:
        discoveries.append({
            "type": "warning",
            "description": "权限不足 (403 Forbidden)",
            "importance": 4
        })
    elif status_code == 404:
        discoveries.append({
            "type": "info",
            "description": "端点不存在 (404 Not Found)",
            "importance": 2
        })
    elif status_code >= 500:
        discoveries.append({
            "type": "error",
            "description": f"服务器错误 ({status_code})",
            "importance": 3
        })
    
    return discoveries


def _analyze_json_structure(data: Any, base_url: str) -> List[Dict[str, Any]]:
    """分析JSON数据结构"""
    discoveries = []
    
    def _traverse(obj: Any, path: str = "", depth: int = 0):
        if depth > 3:  # 防止过深递归
            return
        
        if isinstance(obj, dict):
            # 检查是否有明显的API元数据
            api_keys = ["endpoints", "resources", "apis", "paths", "swagger", "openapi"]
            for key in api_keys:
                if key in obj:
                    discoveries.append({
                        "type": "api_metadata",
                        "key": key,
                        "description": f"发现API元数据: {key}",
                        "importance": 4
                    })
            
            # 检查链接
            link_keys = ["links", "href", "url", "next", "previous", "self"]
            for key in link_keys:
                if key in obj and isinstance(obj[key], str) and obj[key].startswith(("http://", "https://", "/")):
                    discoveries.append({
                        "type": "link",
                        "key": key,
                        "value": obj[key],
                        "description": f"发现链接: {key} = {obj[key][:50]}...",
                        "importance": 3
                    })
            
            # 递归遍历
            for k, v in obj.items():
                _traverse(v, f"{path}.{k}" if path else k, depth + 1)
                
        elif isinstance(obj, list) and len(obj) > 0:
            # 只检查第一个元素
            _traverse(obj[0], f"{path}[0]", depth + 1)
    
    _traverse(data)
    return discoveries


async def explore_api(
    base_url: str,
    max_depth: int = 2,
    current_depth: int = 0,
    visited: Optional[set] = None,
    headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    探索API结构
    
    Args:
        base_url: API基础URL
        max_depth: 最大探索深度
        current_depth: 当前深度
        visited: 已访问的URL集合
        headers: 请求头
        
    Returns:
        探索结果
    """
    if visited is None:
        visited = set()
    
    if current_depth >= max_depth:
        return {"base_url": base_url, "depth": current_depth, "discoveries": []}
    
    if base_url in visited:
        return {"base_url": base_url, "depth": current_depth, "discoveries": []}
    
    visited.add(base_url)
    
    # 获取基础URL
    success, response = await fetch_url(base_url, headers=headers)
    
    discoveries = []
    if success:
        # 分析响应
        discoveries.extend(analyze_api_response(response))
        
        # 寻找子端点
        content = response.get("content")
        if isinstance(content, str):
            # 寻找相对链接
            import urllib.parse
            base_parts = urllib.parse.urlparse(base_url)
            
            # 寻找/api/开头的链接
            api_pattern = r'["\'](/api/[^"\'\s?#]+)["\']'
            api_matches = re.findall(api_pattern, content)
            
            for match in api_matches:
                # 构建完整URL
                if match.startswith("/"):
                    full_url = f"{base_parts.scheme}://{base_parts.netloc}{match}"
                else:
                    full_url = urllib.parse.urljoin(base_url, match)
                
                if full_url not in visited:
                    # 递归探索
                    sub_result = await explore_api(
                        full_url,
                        max_depth=max_depth,
                        current_depth=current_depth + 1,
                        visited=visited,
                        headers=headers
                    )
                    discoveries.extend(sub_result.get("discoveries", []))
    
    return {
        "base_url": base_url,
        "depth": current_depth,
        "discoveries": discoveries,
        "visited_count": len(visited)
    }


def format_api_discoveries(discoveries: List[Dict[str, Any]]) -> str:
    """格式化API发现结果"""
    if not discoveries:
        return "未发现API信息。"
    
    # 按类型分组
    by_type = {}
    for disc in discoveries:
        disc_type = disc.get("type", "unknown")
        if disc_type not in by_type:
            by_type[disc_type] = []
        by_type[disc_type].append(disc)
    
    lines = ["API探索发现:"]
    
    # 按重要性排序显示
    type_order = ["authentication", "api_metadata", "endpoint", "link", "warning", "error", "info"]
    
    for disc_type in type_order:
        if disc_type in by_type:
            type_discoveries = by_type[disc_type]
            
            # 类型标题
            type_names = {
                "authentication": "[AUTH] 认证信息",
                "api_metadata": "[META] API元数据",
                "endpoint": "[ENDP] 端点",
                "link": "[LINK] 链接",
                "warning": "[WARN] 警告",
                "error": "[ERROR] 错误",
                "info": "[INFO] 信息"
            }
            title = type_names.get(disc_type, disc_type)
            lines.append(f"\n{title}:")
            
            for disc in type_discoveries:
                importance = disc.get("importance", 1)
                importance_str = "*" * importance
                
                desc = disc.get("description", "")
                value = disc.get("value", "")
                
                if value:
                    lines.append(f"  {importance_str} {desc}")
                    lines.append(f"    值: {value[:100]}{'...' if len(value) > 100 else ''}")
                else:
                    lines.append(f"  {importance_str} {desc}")
    
    return "\n".join(lines)


async def store_api_discovery(
    discovery: Dict[str, Any],
    chat_id: str = ""
) -> bool:
    """
    存储API发现到记忆系统
    
    Args:
        discovery: 发现信息
        chat_id: 聊天ID（用于个性化存储）
        
    Returns:
        是否成功存储
    """
    try:
        # 导入记忆系统
        from memory.graph_store import GraphStore, CORE_AGENT_NODE_UUID, DEFAULT_DOMAIN
        from memory.ingest import _slugify, _clamp
        import uuid
        
        store = GraphStore()
        
        discovery_type = discovery.get("type", "unknown")
        description = discovery.get("description", "")
        value = discovery.get("value", "")
        importance = discovery.get("importance", 3)
        
        if not description:
            return False
        
        # 构建记忆内容
        summary = f"API发现[{discovery_type}]: {description[:80]}"
        content = json.dumps({
            "type": discovery_type,
            "description": description,
            "value": value,
            "importance": importance,
            "discovered_at": datetime.now().isoformat(),
            "chat_id": chat_id
        }, ensure_ascii=False, indent=2)
        
        # 创建路径
        base_path = _slugify(f"api_discovery/{discovery_type}/{description[:30]}")
        domain = DEFAULT_DOMAIN
        
        # 检查是否已存在
        eid = store.get_edge_id_by_path(domain, base_path)
        node_uuid = None
        
        if eid:
            node_uuid = store.get_child_uuid_by_edge_id(eid)
        
        if not node_uuid:
            node_uuid = str(uuid.uuid4())
        
        # 存储记忆版本
        memory_id = store.create_or_update_memory_version(
            node_uuid=node_uuid,
            content=content,
            summary=summary,
            importance=_clamp(importance),
            is_permanent=importance >= 4
        )
        
        # 添加边
        disclosures = [f"API探索发现: {discovery_type}"]
        for d in disclosures:
            edge_id = store.add_edge(
                CORE_AGENT_NODE_UUID,
                node_uuid,
                d,
                priority=_clamp(importance)
            )
            store.add_or_replace_path(domain, base_path, edge_id)
        
        # 标记使用
        store.mark_memory_used(memory_id, f"api_exploration from chat:{chat_id}")
        
        return True
        
    except Exception as e:
        print(f"❌ 存储API发现失败: {e}")
        return False


async def explore_and_learn(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Any] = None,
    chat_id: str = "",
    store_discoveries: bool = True
) -> str:
    """
    探索URL并学习API，返回格式化结果
    
    Args:
        url: 目标URL
        method: HTTP方法
        headers: 请求头
        body: 请求体
        chat_id: 聊天ID
        store_discoveries: 是否存储发现到记忆系统
        
    Returns:
        格式化结果字符串
    """
    # 发送请求
    success, response = await fetch_url(url, method=method, headers=headers, body=body)
    
    if not success:
        return f"❌ 请求失败: {response.get('error', '未知错误')}"
    
    # 分析响应
    discoveries = analyze_api_response(response)
    
    # 存储重要发现
    if store_discoveries and discoveries:
        stored_count = 0
        for disc in discoveries:
            if disc.get("importance", 1) >= 3:  # 重要性3及以上才存储
                if await store_api_discovery(disc, chat_id):
                    stored_count += 1
        
        if stored_count > 0:
            print(f"🧠 存储了 {stored_count} 条API发现到记忆系统")
    
    # 格式化结果
    status_code = response.get("status_code", 0)
    content_type = response.get("content_type", "")
    size = response.get("size", 0)
    
    result_lines = [
        f"请求 {method} {url}",
        f"状态: {status_code} | 类型: {content_type} | 大小: {size} 字节",
        ""
    ]
    
    # 添加发现
    if discoveries:
        result_lines.append(format_api_discoveries(discoveries))
    else:
        result_lines.append("未发现明显的API信息。")
    
    # 添加响应预览
    result_lines.append("\n响应预览:")
    content = response.get("content")
    
    if isinstance(content, dict):
        preview = json.dumps(content, ensure_ascii=False)[:500]
        if len(json.dumps(content, ensure_ascii=False)) > 500:
            preview += "..."
        result_lines.append(preview)
    elif isinstance(content, str):
        if len(content) > 500:
            result_lines.append(content[:500] + "...")
        else:
            result_lines.append(content)
    
    return "\n".join(result_lines)
