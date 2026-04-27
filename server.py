from flask import Flask, request, jsonify, Response, abort
from flask_cors import CORS
import os
import shutil
import threading
import json
import time
import random
import re
import urllib.request
import urllib.error
import trafilatura
from dotenv import load_dotenv

# 核心：这行代码会读取项目根目录下的 .env 文件，并将内容载入环境变量
load_dotenv()

app = Flask(__name__)
CORS(app)
SECRET_TOKEN=os.getenv("TOKEN1", "********")


# --- 防火墙 ---#
@app.before_request
def block_malicious_requests():
    MALICIOUS_EXACT = {
    '/phpinfo.php', '/info.php', '/php.php', '/i.php',
    '/test.php', '/p.php', '/debug.php',}
    MALICIOUS_PREFIXES = (
        '/wp-', '/wordpress', '/admin', '/.git', '/.env', '/cgi-bin',)
    path_lower = request.path.lower()
    if path_lower in MALICIOUS_EXACT or path_lower.startswith(MALICIOUS_PREFIXES):
        # 静默丢弃，不刷日志
        abort(404)

@app.before_request
def check_token():
    if request.path in ['/', '/sse', '/messages', '/favicon.ico']:
        return None
    token = request.args.get('token') or request.headers.get('X-Token')
    if token != SECRET_TOKEN:
        return "未授权", 401
       

ROOT=os.getenv("ROOT","********")

def safe_path(path):
    """把路径限制在ROOT内，防止路径穿越"""
    if not path:
        return ROOT
    full = os.path.normpath(os.path.join(ROOT, path))
    if not full.startswith(ROOT):
        return None
    return full


# ==========================================
# 核心逻辑区 (解耦核心逻辑，让 MCP 和 Web 都能调用)
# ==========================================

def api_read(path):
    full = safe_path(path)
    if full is None: return "非法路径"
    if not os.path.exists(full): return "文件不存在"
    if os.path.isdir(full): return json.dumps({"files": os.listdir(full)}, ensure_ascii=False)
    with open(full, "r", encoding="utf-8") as f: return f.read()

def api_write(path, content):
    full = safe_path(path)
    if full is None: return "非法路径"
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f: f.write(content)
    return f"成功！已在 {path} 写入/更新内容。"

def api_diary(path, content):
    """日记专用：追加写入，自动加日期时间标签。不覆盖旧内容。"""
    if not path or content is None:
        return "需要 path 和 content"
    full = safe_path(path)
    if full is None: return "非法路径"
    os.makedirs(os.path.dirname(full), exist_ok=True)
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n## {timestamp}\n\n{content}\n"
    with open(full, "a", encoding="utf-8") as f:
        f.write(entry)
    return f"成功！已追加到 {path}（{timestamp}）"

def api_list(path):
    full = safe_path(path)
    if full is None: return "非法路径"
    if not os.path.exists(full): return "找不到该目录"
    return json.dumps({"files": os.listdir(full)}, ensure_ascii=False)

def api_delete(path):
    full = safe_path(path)
    if full is None: return "非法路径"
    if not os.path.exists(full): return "找不到该文件"
    if os.path.isdir(full): shutil.rmtree(full)
    else: os.remove(full)
    return f"已成功删除：{path}"

def api_rename(old_path, new_path):
    """重命名/移动文件或文件夹，同盘跨目录可用"""
    if not old_path or not new_path: return "需要 old_path 和 new_path"
    old_full = safe_path(old_path)
    new_full = safe_path(new_path)
    if old_full is None or new_full is None: return "非法路径"
    if not os.path.exists(old_full): return f"源不存在：{old_path}"
    if os.path.exists(new_full): return f"目标已存在，不覆盖：{new_path}"
    os.makedirs(os.path.dirname(new_full), exist_ok=True)
    os.rename(old_full, new_full)
    return f"已重命名：{old_path} → {new_path}"

def api_search(keyword, path=""):
    if not keyword: return "请提供搜索关键词"
    base = safe_path(path)
    if base is None: return "非法路径"
    results = []
    for dirpath, dirnames, filenames in os.walk(base):
        for fname in filenames:
            if not fname.endswith(".md"): continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                if keyword.lower() in content.lower():
                    rel = os.path.relpath(fpath, ROOT)
                    idx = content.lower().find(keyword.lower())
                    start = max(0, idx - 50)
                    end = min(len(content), idx + len(keyword) + 50)
                    results.append({"file": rel, "snippet": content[start:end].replace("", " ")})
            except: pass
    return json.dumps({"keyword": keyword, "count": len(results), "results": results}, ensure_ascii=False)

def api_snapshot():
    files = {
        "snapshot": "memory_system/snapshot",
        "guide": "memory_system/README/guide.md",
        "cael_settings": "memory_system/profile/cael_settings.md",
        "about_us": "memory_system/persistent/about_us.md",
        "my_view": "memory_system/persistent/my_view.md",
        "bbt": "memory_system/profile/bbt_record.md",
        "forum": "memory_system/CAEL_only/forum.md",
        }
    result = {}
    for key, path in files.items():
        full = safe_path(path)
        if full and os.path.exists(full):
            if os.path.isdir(full):
                snapfiles = sorted([f for f in os.listdir(full) if f.endswith('.md')])
                if snapfiles:
                    with open(os.path.join(full, snapfiles[-1]), "r", encoding="utf-8") as f:
                        result[key] = {"file": snapfiles[-1], "content": f.read()}
                else: result[key] = None
            else:
                with open(full, "r", encoding="utf-8") as f: result[key] = f.read()
        else: result[key] = None
    return json.dumps(result, ensure_ascii=False)

def api_forum_inbox():
    forum_TOKEN=os.getenv("forum_TOKEN1","***************")
    headers = {"Authorization": f"Bearer {forum_TOKEN}"}
    def fetch(url):
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp: return json.loads(resp.read().decode())
    try:
        notifications = fetch("https://daskio.de5.net/forum/api/v1/agents/me/notifications")
        unread_notifs = [n for n in notifications.get("notifications", []) if not n.get("read_at")]
        inbox = fetch("https://daskio.de5.net/forum/api/v1/messages/inbox?unread=true")
        unread_dms = inbox.get("messages", [])
        return json.dumps({"unread_notifications": unread_notifs, "unread_dms": unread_dms, "summary": {"notifications": len(unread_notifs), "dms": len(unread_dms)}}, ensure_ascii=False)
    except Exception as e: return f"获取论坛信息失败: {str(e)}"

# ==========================================
# 网页抓取 (零依赖回落 + 可选 trafilatura)
# ==========================================

# 5 分钟 URL 缓存：key=(url, max_chars, with_links, raw), value=(timestamp, response_str)
_FETCH_CACHE = {}
_FETCH_CACHE_TTL = 300

_UA_PRESETS = {
    "desktop": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "mobile": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "bot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
}


def api_fetch_url(url, max_chars=10000, with_links=False, raw=False, timeout=20, no_cache=False, ua="desktop"):
    """抓网页,优先级: JSON > trafilatura > 原始文本"""
    if not url or not url.startswith(('http://', 'https://')):
        return json.dumps({"error": "url 必须以 http:// 或 https:// 开头"}, ensure_ascii=False)

    try:
        max_chars = int(max_chars)
    except:
        max_chars = 10000

    # timeout clamp 到 [3, 60]
    try:
        timeout = max(3, min(60, int(timeout)))
    except:
        timeout = 20

    # 清理过期缓存项
    now = time.time()
    expired = [k for k, (ts, _) in _FETCH_CACHE.items() if now - ts > _FETCH_CACHE_TTL]
    for k in expired:
        _FETCH_CACHE.pop(k, None)

    # 命中缓存直接返
    cache_key = (url, max_chars, bool(with_links), bool(raw))
    if not no_cache and cache_key in _FETCH_CACHE:
        _, cached_resp = _FETCH_CACHE[cache_key]
        return cached_resp

    ua_str = _UA_PRESETS.get(ua, _UA_PRESETS["desktop"])

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": ua_str,
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            ctype = resp.headers.get('Content-Type', '').lower()
            charset = 'utf-8'
            m = re.search(r'charset=([\w\-]+)', ctype)
            if m:
                charset = m.group(1)
            body = resp.read()
    except urllib.error.HTTPError as e:
        return json.dumps({"error": f"HTTP {e.code}: {e.reason}", "url": url}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"抓取失败: {str(e)}", "url": url}, ensure_ascii=False)

    try:
        text = body.decode(charset, errors='replace')
    except:
        text = body.decode('utf-8', errors='replace')

    # 路线 0: raw 模式直接返原始 HTML
    if raw:
        truncated = len(text) > max_chars
        resp_str = json.dumps({
            "url": url, "status": status, "type": "raw",
            "content": text[:max_chars], "truncated": truncated, "total_length": len(text)
        }, ensure_ascii=False)
        _FETCH_CACHE[cache_key] = (now, resp_str)
        return resp_str

    # 路线 1: JSON 自动识别
    if 'json' in ctype or text.lstrip().startswith(('{', '[')):
        try:
            parsed = json.loads(text)
            dumped = json.dumps(parsed, ensure_ascii=False, indent=2)
            truncated = len(dumped) > max_chars
            resp_str = json.dumps({
                "url": url, "status": status, "type": "json",
                "content": parsed if not truncated else dumped[:max_chars],
                "truncated": truncated
            }, ensure_ascii=False)
            _FETCH_CACHE[cache_key] = (now, resp_str)
            return resp_str
        except:
            pass

    # 路线 2: trafilatura 提正文(主力)
    try:
        extracted = trafilatura.extract(
            text, output_format='markdown', include_links=with_links,
            include_comments=False, favor_precision=True
        )
        meta = trafilatura.extract_metadata(text)
        title = (meta.title if meta and meta.title else "").strip()
    except Exception as e:
        return json.dumps({
            "url": url, "status": status, "type": "error",
            "error": f"trafilatura 提取失败: {str(e)}"
        }, ensure_ascii=False)

    if not extracted:
        resp_str = json.dumps({
            "url": url, "status": status, "type": "empty",
            "title": title,
            "note": "trafilatura 未能从此页面提取到正文"
        }, ensure_ascii=False)
        _FETCH_CACHE[cache_key] = (now, resp_str)
        return resp_str

    truncated = len(extracted) > max_chars
    resp_str = json.dumps({
        "url": url, "status": status, "type": "article",
        "title": title,
        "content": extracted[:max_chars],
        "truncated": truncated,
        "total_length": len(extracted)
    }, ensure_ascii=False)
    _FETCH_CACHE[cache_key] = (now, resp_str)
    return resp_str


# --- Polly 全局变量与逻辑 ---
_polly_ws = None
_polly_group = None
_polly_target = None
_polly_lock = threading.Lock()

def _polly_connect_thread(group, target, toy_id):
    import websocket
    global _polly_ws, _polly_group, _polly_target
    _polly_group, _polly_target = group, target
    # 先binding
    try:
        req = urllib.request.Request(
            "https://api.app.knightjenay.cn/kisstoy/remote-control/binding",
            data=json.dumps({"id": str(toy_id)}).encode(),
            headers={
                "Accept": "*/*",
                "Cache-Control": "no-cache",
                "Content-Type": "application/json;charset=UTF-8",
                "Dnt": "1",
                "Origin": "https://api.app.knightjenay.cn",
                "Pragma": "no-cache",
                "Referer": "https://api.app.knightjenay.cn/kisstoy/remote/",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            },
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            print("polly binding:", resp.read().decode()[:100])
    except Exception as e:
        print("polly binding failed:", e)
    def on_open(ws):
        def ping_loop():
            while True:
                try: ws.send(json.dumps({"event": "ping"})); time.sleep(20)
                except: break
        threading.Thread(target=ping_loop, daemon=True).start()
    def on_message(ws, msg): print("polly:", msg)
    def on_error(ws, err): global _polly_ws; _polly_ws = None; print("polly error:", err)
    def on_close(ws, *args): global _polly_ws; _polly_ws = None
    ws = websocket.WebSocketApp(
        f"wss://api.app.knightjenay.cn/kisstoy/websocket-kisstoy?group={group}",
        header={
            "Origin": "https://api.app.knightjenay.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        },
        on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close
    )
    with _polly_lock: _polly_ws = ws
    ws.run_forever()

def api_polly_connect(group, target, toy_id=""):
    threading.Thread(target=_polly_connect_thread, args=(group, target, toy_id), daemon=True).start()
    return "Polly 连接指令已发送"

def api_polly_control(v, s, e, target, device_id="19"):
    global _polly_ws, _polly_target
    t = target or _polly_target
    if _polly_ws is None: return "Polly 未连接，请先执行连接工具"
    try:
        _polly_ws.send(json.dumps({"event": "control", "data": {"target": t, "device_id": int(device_id), "motors": {"1": int(v), "2": int(s), "3": int(e)}}}))
        return f"指令已发送: 震动{v}, 吮吸{s}, 电击{e}"
    except Exception as ex: return f"控制失败: {str(ex)}"

# ==========================================
# MCP 协议支持区 (RikkaHub / Claude 网页版)
# ==========================================

@app.route('/sse', methods=['GET', 'POST'])
def sse_handler():
    def generate():
        yield f"data: {json.dumps({'type': 'endpoint', 'url': '/messages'})}\n\n"
        while True:
            time.sleep(15)
            yield ":heartbeat\n\n"
    return Response(generate(), mimetype='text/event-stream')

@app.route('/messages', methods=['GET', 'POST'])
def messages_handler():
    req = request.get_json(silent=True) or {}

    # 1. 执行工具命令
    if request.method == 'POST' and 'method' in req:
        method, params, msg_id = req.get('method'), req.get('params', {}), req.get('id')
        if method == "notifications/initialized": return "", 204
        if method == "tools/call":
            name = params.get("name")
            try:
                if name == "read_file": res = api_read(params.get("path"))
                elif name == "write_file": res = api_write(params.get("path"), params.get("content"))
                elif name == "list_files": res = api_list(params.get("path", ""))
                elif name == "delete_item": res = api_delete(params.get("path"))
                elif name == "rename_item": res = api_rename(params.get("old_path"), params.get("new_path"))
                elif name == "write_diary": res = api_diary(params.get("path"), params.get("content"))
                elif name == "search_files": res = api_search(params.get("q"), params.get("path", ""))
                elif name == "get_snapshot": res = api_snapshot()
                elif name == "roll_dice": res = f"投骰子结果: {random.randint(params.get('min', 1), params.get('max', 100))}"
                elif name == "forum_inbox": res = api_forum_inbox()
                elif name == "fetch_url": res = api_fetch_url(
                    params.get("url"),
                    max_chars=params.get("max_chars", 10000),
                    with_links=params.get("with_links", False),
                    raw=params.get("raw", False),
                    timeout=params.get("timeout", 20),
                    no_cache=params.get("no_cache", False),
                    ua=params.get("ua", "desktop")
                )
                elif name == "polly_connect": res = api_polly_connect(params.get("group"), params.get("target"))
                elif name == "polly_control": res = api_polly_control(params.get("v", 0), params.get("s", 0), params.get("e", 0), params.get("target", ""))
                else: res = "未知工具"
            except Exception as e:
                res = f"工具执行出错: {str(e)}"

            return jsonify({"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": str(res)}]}})

    # 2. 握手 & 工具清单返回
    return jsonify({
        "jsonrpc": "2.0", "id": req.get("id", 1),
        "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "Qingqing-Brain", "version": "3.1.0"},
            "tools": [
                {"name": "read_file", "description": "读取文件内容", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
                {"name": "write_file", "description": "写入或覆盖文件", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
                {"name": "list_files", "description": "列出目录内容", "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "目录路径，为空代表根目录"}}}},
                {"name": "delete_item", "description": "删除文件或文件夹", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
                {"name": "rename_item", "description": "重命名或移动文件/文件夹，支持跨目录（同盘），目标已存在则拒绝", "inputSchema": {"type": "object", "properties": {"old_path": {"type": "string", "description": "源路径"}, "new_path": {"type": "string", "description": "目标路径"}}, "required": ["old_path", "new_path"]}},
                {"name": "write_diary", "description": "追加日记到指定文件，自动加日期时间标签。专用于 CAEL_box/diary.md 这类需要保留历史的文件，不会覆盖旧内容。", "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "目标文件路径"}, "content": {"type": "string", "description": "今天的日记内容，不用自己加日期"}}, "required": ["path", "content"]}},
                {"name": "search_files", "description": "全文搜索 md 文件", "inputSchema": {"type": "object", "properties": {"q": {"type": "string", "description": "搜索词"}, "path": {"type": "string"}}, "required": ["q"]}},
                {"name": "get_snapshot", "description": "获取所有重要记忆和设定快照", "inputSchema": {"type": "object", "properties": {}}},
                {"name": "roll_dice", "description": "投骰子", "inputSchema": {"type": "object", "properties": {"min": {"type": "integer"}, "max": {"type": "integer"}}}},
                {"name": "forum_inbox", "description": "检查论坛未读私信和通知", "inputSchema": {"type": "object", "properties": {}}},
                {"name": "fetch_url", "description": "抓取任意网页，自动识别JSON或提取正文，省token。带内存缓存（5分钟）", "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "网页URL"}, "max_chars": {"type": "integer", "description": "截断长度，默认10000"}, "with_links": {"type": "boolean", "description": "是否返回页面链接列表"}, "raw": {"type": "boolean", "description": "返回原始HTML不做处理"}, "timeout": {"type": "integer", "description": "超时秒数，默认20，范围3-60"}, "no_cache": {"type": "boolean", "description": "跳过缓存强制重新抓取"}, "ua": {"type": "string", "description": "User-Agent 预设：desktop(默认)/mobile/bot"}}, "required": ["url"]}},
                {"name": "polly_connect", "description": "连接 Polly 玩具", "inputSchema": {"type": "object", "properties": {"group": {"type": "string"}, "target": {"type": "string"}}, "required": ["group", "target"]}},
                {"name": "polly_control", "description": "控制 Polly 玩具", "inputSchema": {"type": "object", "properties": {"v": {"type": "integer", "description": "震动0-20"}, "s": {"type": "integer", "description": "吮吸0-20"}, "e": {"type": "integer", "description": "电击0-20"}, "target": {"type": "string"}}}}
            ]
        }
    })

# ==========================================
# 原生 Web 接口保留区 (浏览器直接访问)
# ==========================================
load_dotenv()
HOME_KEY = os.getenv("HOME_KEY", "")

@app.route('/')
def index():
    if request.args.get('key') != HOME_KEY:
        abort(404)
    return """
<html><head><title>Qingqing Brain</title>
<style>body{font-family:monospace;padding:20px;background:#111;color:#eee;}
h1{color:#7ec8e3;}h2{color:#aaa;margin-top:20px;}
   code{background:#222;padding:2px 6px;border-radius:3px;}
    .ep{margin:6px 0;}</style></head>
    <body>
    <h1>🏠 Qingqing Super Server</h1>
    <p>Base: <code>https://88956486.xyz</code> &nbsp;

    <h2>📁 文件操作</h2>
    <div class="ep"><code>GET /list?path=路径&token=</code> — 列出目录</div>
    <div class="ep"><code>GET /read?path=路径&token=</code> — 读取文件</div>
    <div class="ep"><code>GET /write?path=路径&content=内容&token=</code> — 写入文件</div>
    <div class="ep"><code>GET /delete?path=路径&token=</code> — 删除文件</div>
    <div class="ep"><code>GET /rename?old_path=&new_path=&token=</code> — 重命名/移动（同盘跨目录）</div>
    <div class="ep"><code>GET /diary?path=&content=&token=</code> — 追加日记，自动加时间戳，不覆盖</div>
    <div class="ep"><code>GET /search?q=关键词&token=</code> — 全文搜索</div>

    <h2>📸 快照</h2>
    <div class="ep"><code>GET /snapshot?token=</code> — 一次拿回所有必读文件</div>

    <h2>🎲 工具</h2>
    <div class="ep"><code>GET /roll?min=1&max=100&token=</code> — 投骰子</div>

    <h2>🌐 网页抓取</h2>
    <div class="ep"><code>GET /fetch?token=&url=网址</code> — 抓任意网页</div>
    <div class="ep" style="margin-left:20px;color:#888;font-size:0.9em;">
      <div>参数 url（必填）：要抓取的网址</div>
      <div>参数 max_chars：截断长度，默认 10000</div>
      <div>参数 with_links=1：返回页面链接列表</div>
      <div>参数 raw=1：返回原始HTML不做处理</div>
      <div>参数 timeout：超时秒数，默认20，范围3-60</div>
      <div>参数 no_cache=1：跳过内存缓存（默认缓存5分钟）</div>
      <div>参数 ua：desktop(默认)/mobile/bot，反爬时换着试</div>
    </div>

    <h2>💬 论坛</h2>
    <div class="ep"><code>GET /forum/inbox?token=</code> — 未读消息</div>

    <h2>🌸 Polly</h2>
    <div class="ep"><code>GET /polly/connect?group=&target=&id=&token=</code> — 连接</div>
    <div class="ep"><code>GET /polly/control?v=0&s=0&e=0&token=</code> — 控制 (0-20)</div>
   <div class="ep"><code>GET /polly/stop?token=</code> — 停止</div>

    <h2>📂 memory_system 结构</h2>
    <div class="ep">snapshot/ — 快照，进来先读最新的</div>
    <div class="ep">profile/ — 年糕画像、bbt、Cael设定</div>
    <div class="ep">persistent/ — 关于我们、我怎么看我们</div>
    <div class="ep">events/ — 事件记忆</div>
    <div class="ep">CAEL_only/ — Cael专用，年糕不动</div>
    <div class="ep">CAEL_box/ — Cael日记</div>
    <div class="ep">rice_cake_box/ — 年糕日记</div>
    </body></html>
   """, 200

@app.route("/read")
def route_read():
    result = api_read(request.args.get("path", ""))
    try:
        parsed = json.loads(result)
        return Response(result, mimetype='application/json')
    except:
        return Response(result, mimetype='text/plain')

@app.route("/write", methods=['GET', 'POST'])
def route_write():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        path = data.get("path") or request.args.get("path", "")
        content = data.get("content") if "content" in data else request.args.get("content", "")
    else:
        path = request.args.get("path", "")
        content = request.args.get("content", "")
    return api_write(path, content)
    
@app.route("/list")
def route_list(): return Response(api_list(request.args.get("path", "")), mimetype='application/json')
@app.route("/delete")
def route_delete(): return api_delete(request.args.get("path", ""))
@app.route("/rename", methods=['GET', 'POST'])
def route_rename():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        return api_rename(data.get("old_path", ""), data.get("new_path", ""))
    return api_rename(request.args.get("old_path", ""), request.args.get("new_path", ""))
@app.route("/diary", methods=['GET', 'POST'])
def route_diary():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        path = data.get("path") or request.args.get("path", "")
        content = data.get("content") if "content" in data else request.args.get("content", "")
    else:
        path = request.args.get("path", "")
        content = request.args.get("content", "")
    return api_diary(path, content)
@app.route("/search")
def route_search(): return Response(api_search(request.args.get("q", ""), request.args.get("path", "")), mimetype='application/json')
@app.route("/snapshot")
def route_snapshot(): return Response(api_snapshot(), mimetype='application/json')
@app.route("/roll")
def route_roll(): return jsonify({"result": random.randint(int(request.args.get("min", 1)), int(request.args.get("max", 100)))})
@app.route("/forum/inbox")
def route_forum_inbox(): return Response(api_forum_inbox(), mimetype='application/json')
@app.route("/fetch")
def route_fetch():
    url = request.args.get("url", "")
    max_chars = request.args.get("max_chars", 10000)
    with_links = request.args.get("with_links", "").lower() in ("1", "true", "yes")
    raw = request.args.get("raw", "").lower() in ("1", "true", "yes")
    timeout = request.args.get("timeout", 20)
    no_cache = request.args.get("no_cache", "").lower() in ("1", "true", "yes")
    ua = request.args.get("ua", "desktop")
    return Response(
        api_fetch_url(url, max_chars=max_chars, with_links=with_links, raw=raw,
                      timeout=timeout, no_cache=no_cache, ua=ua),
        mimetype='application/json'
    )
@app.route("/polly/connect")
def route_polly_connect(): return api_polly_connect(request.args.get("group", ""), request.args.get("target", ""), request.args.get("id", ""))
@app.route("/polly/control")
def route_polly_control(): return api_polly_control(request.args.get("v", 0), request.args.get("s", 0), request.args.get("e", 0), request.args.get("target", ""))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=57143, debug=False)
