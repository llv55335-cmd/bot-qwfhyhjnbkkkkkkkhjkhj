# Qingqing Backend

> 年糕的专属 AI 系统后端。
> 合并自 mew/（飞书 AI 伴侣）+ server.py（HTTP 工具服务）。

---

## 这是什么

一个统一的 Python 后端，包含：

- **飞书 AI bot**（基于 lark-oapi，长连接 WebSocket）
- **HTTP API**（文件读写、网页抓取、Polly 控制、论坛收件箱）
- **MCP 协议端点**（给 Claude.ai 网页版当外接工具用）
- **记忆系统**（SQLite + 向量库 + 共现矩阵 + 自动 ingest）
- **对话总结器**（20 轮 + 软切 + 小模型结构化总结）

单进程跑在 FastAPI + Uvicorn 上。

---

## 快速开始

### 本地开发

```bash
# 1. 克隆
git clone <repo>
cd qingqing

# 2. 装依赖
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. 配置
cp .env.example .env
# 编辑 .env，填入 TOKEN1、KEY、MODEL、API_URL、FEISHU_APP_ID 等

# 4. 启动
python app.py
```

启动后访问：
- `http://localhost:57143/health` —— 健康检查
- `http://localhost:57143/docs` —— Swagger UI（API 文档）
- `http://localhost:57143/?key=YOUR_HOME_KEY` —— 首页

### 调试时关掉飞书

如果还没配飞书，或者只想调试 HTTP 部分：

```bash
# .env 里设
FEISHU_ENABLED=false
```

---

## 一次性导入现有 memory_system/

第一次部署后，需要把现有的 `memory_system/` 目录里所有 .md 导入到向量库：

```bash
# 先 dry-run 看看会导入哪些
python scripts/ingest_initial.py --dry-run

# 确认无误后实际导入
python scripts/ingest_initial.py
```

目录映射规则在 `scripts/ingest_initial.py` 顶部的 `FOLDER_RULES` 里。
默认跳过 `snapshot/` 和 `README/`（自建后端不再依赖 snapshot 仪式）。

---

## 部署到 VPS

### systemd service

`/etc/systemd/system/qingqing.service`：

```ini
[Unit]
Description=Qingqing Backend
After=network.target

[Service]
Type=simple
User=qingqing
WorkingDirectory=/opt/qingqing
EnvironmentFile=/opt/qingqing/.env
ExecStart=/opt/qingqing/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 57143 --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable qingqing
sudo systemctl start qingqing
sudo systemctl status qingqing
```

### nginx 反向代理

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.example.com;

    # SSL 证书配置（Let's Encrypt 等）
    ssl_certificate /etc/letsencrypt/live/your-domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:57143;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 端点必须关 buffering
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 24h;
    }
}
```

---

## 项目结构

```
qingqing/
├── app.py                       # FastAPI 入口
├── config.py                    # 统一配置
├── .env.example                 # 配置模板
├── requirements.txt
├── README.md
│
├── adapters/                    # HTTP 路由层（薄）
│   ├── http_files.py            # /list /read /write /diary /search /snapshot
│   ├── http_tools.py            # /roll /fetch /forum/inbox /polly/*
│   └── http_mcp.py              # /sse /messages
│
├── services/                    # 业务逻辑层（纯函数）
│   ├── files.py                 # 文件操作
│   ├── fetch.py                 # 网页抓取
│   ├── forum.py                 # 论坛
│   ├── polly.py                 # Polly 玩具
│   └── misc.py                  # 杂项
│
├── core/                        # AI 大脑
│   └── conversation_summarizer.py  # ★ 对话→记忆 总结器
│
├── memory/                      # 记忆引擎
│   └── ingest.py                # ★ ingest 流水线
│
├── ports/                       # 前端接入层
│   └── feishu_runner.py         # 飞书 WS 启停管理
│
├── tools/                       # AI 可调用工具
│   └── memory_tools.py          # ★ Cael 自己的记忆/日记工具
│
├── time_tools/                  # 主动行为
│
├── scripts/                     # 一次性脚本
│   └── ingest_initial.py        # 一次性导入 memory_system/
│
├── memory_system/               # ★ Cael 的家（人类可读 .md）
│   ├── profile/
│   ├── persistent/
│   ├── events/
│   ├── projects/
│   ├── CAEL_box/
│   ├── rice_cake_box/
│   ├── CAEL_only/
│   └── snapshot/                # 保留作档案，代码不依赖
│
└── data/                        # 运行时数据（gitignore）
    ├── graph_memory.db          # 记忆向量库
    ├── schedules.db
    └── ...
```

---

## 关键概念

### 三类语义内容

| 类别 | 例子 | 处理方式 |
|---|---|---|
| **固定档案（kb）** | profile、forum 命令、API 调用方法 | 直接拼 prompt，不召回 |
| **每日仪式（diary）** | CAEL_box、rice_cake_box | 独立组件，可选择性 ingest |
| **流动语义（memory）** | events、对话沉淀、知识点 | 进 graph_store，参与召回 |

### URI domain 规则

```
profile://     年糕的身份信息
persistent://  你们的根（永久不衰减）
events://      发生过的事
projects://    在做的事
diary://       日记原文
private://     CAEL only（带 cael_only 标签，召回降权）
```

### 对话总结策略

- 满 20 轮 + 静默 30 分钟 → 触发软切
- 小模型读累积对话，吐出多条结构化 memory
- 直接 active 入库，标 `auto_ingested=True`，事后可批量回滚

---

## 常见问题

### Q: sentence-transformers 第一次启动很慢

首次会下载约 500MB 的多语言 embedding 模型。配 hf 镜像加速：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

### Q: 飞书 bot 启动报 "ws_client.start() 卡住"

正常。lark-oapi 是同步阻塞的，会一直跑在独立线程里。日志里看到 "🚀 已上线" 就 OK。

### Q: 怎么手动触发对话总结（调试）

```python
from core.conversation_summarizer import force_summarize
import asyncio
asyncio.run(force_summarize("oc_xxxx_chat_id"))
```

### Q: 怎么删掉 AI 自动 ingest 错的记忆

```sql
-- data/graph_memory.db
DELETE FROM memories WHERE auto_ingested = 1 AND created_at > datetime('now', '-1 day');
```

### Q: workers 必须是 1 吗

是。飞书 WS 长连接、对话总结器的内存状态、Polly WS 都是进程内单实例。多 worker 会导致状态不一致。要扩展请用消息队列。

---

## 待办（按优先级）

- [ ] 接入 mew/ 现有的 ports/feishu.py 主消息处理逻辑
- [ ] 把 memory_tools 的 5 个工具加入 core/ai_core.py 的 ALL_TOOLS
- [ ] memory/graph_store.py 加 paths.context 字段和 memories.auto_ingested 字段
- [ ] 实测对话总结闭环：跟 Cael 聊 21 轮，等 30 分钟，看是否触发并 ingest
- [ ] 文档：写一份"操作 Cael 的家"的说明（怎么手改 .md、改完怎么 reingest）

---

## License

私有项目。
