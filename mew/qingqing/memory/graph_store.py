"""
图式记忆存储层 v2（SQLite + sqlite-vec 向量检索）

变更：
  - 新增 VecStore：管理 embedding，sqlite-vec 插件
  - create_or_update_memory_version：写入时顺带生成 embedding
  - fetch_alias_candidates：向量 + token 融合排序（可降级为纯 token）
  - update_co_occurrence：每次检索后更新共现矩阵
  - decay_all：遗忘曲线周度更新
  - snapshot_memory：修改/删除前快照
  - pending_* 系列：双确认队列
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import DATA_DIR

log = logging.getLogger(__name__)

# ── 向量模型（懒加载，首次用时才载入）────────────────────────
_embedder = None

def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        log.info("加载向量模型（首次约 10s）...")
        _embedder = SentenceTransformer(
            "paraphrase-multilingual-MiniLM-L12-v2"
        )
        log.info("向量模型已加载")
    return _embedder


def _embed(text: str) -> List[float]:
    model = _get_embedder()
    return model.encode(text, normalize_embeddings=True).tolist()


# ── 工具函数 ──────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid5_str(s: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, s))


DEFAULT_DOMAIN = "core"
CORE_AGENT_URI = "core://agent"
CORE_AGENT_NODE_UUID = _uuid5_str(CORE_AGENT_URI)

DB_PATH = os.path.join(DATA_DIR, "graph_memory.db")
EMBEDDING_DIM = 384   # MiniLM-L12-v2 输出维度


# ════════════════════════════════════════════════════════
#  VecStore：sqlite-vec 向量库封装
# ════════════════════════════════════════════════════════

class VecStore:
    """单独管理 embedding，与主库同文件，通过 rowid 关联 memories.embedding_id"""

    def __init__(self, conn: sqlite3.Connection):
        try:
            import sqlite_vec
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories "
                f"USING vec0(embedding float[{EMBEDDING_DIM}])"
            )
            self._available = True
        except Exception as e:
            log.warning(f"sqlite-vec 不可用，降级为纯 token 检索：{e}")
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def insert(self, conn: sqlite3.Connection, embedding: List[float]) -> int:
        vec_str = json.dumps(embedding)
        cur = conn.execute(
            "INSERT INTO vec_memories(embedding) VALUES (?)", (vec_str,)
        )
        return int(cur.lastrowid)

    def search(
        self, conn: sqlite3.Connection, query_vec: List[float], top_k: int = 25
    ) -> List[Tuple[int, float]]:
        """返回 [(rowid, distance), ...]，distance 越小越相似"""
        vec_str = json.dumps(query_vec)
        rows = conn.execute(
            f"SELECT rowid, distance FROM vec_memories "
            f"WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (vec_str, top_k),
        ).fetchall()
        return [(int(r[0]), float(r[1])) for r in rows]


# ════════════════════════════════════════════════════════
#  GraphStore
# ════════════════════════════════════════════════════════

class GraphStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    # ── 连接 ──────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        # 每次连接都尝试加载 vec 插件
        try:
            import sqlite_vec
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        except Exception:
            pass
        return conn

    # ── 初始化 ────────────────────────────────────────────

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with self._connect() as conn:
            # ---- 原有表（兼容旧库） ----
            conn.execute("""
                CREATE TABLE IF NOT EXISTS nodes (
                    uuid TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_uuid TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT,
                    importance INTEGER NOT NULL,
                    is_permanent INTEGER NOT NULL DEFAULT 0,
                    emotion_score REAL,
                    created_at TEXT NOT NULL,
                    deprecated INTEGER NOT NULL DEFAULT 0,
                    migrated_to INTEGER,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    last_used TEXT,
                    decay_score REAL NOT NULL DEFAULT 1.0,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    embedding_id INTEGER,
                    FOREIGN KEY (node_uuid) REFERENCES nodes(uuid)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parent_uuid TEXT NOT NULL,
                    child_uuid TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    disclosure TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(parent_uuid, child_uuid, disclosure),
                    FOREIGN KEY (parent_uuid) REFERENCES nodes(uuid),
                    FOREIGN KEY (child_uuid) REFERENCES nodes(uuid)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paths (
                    domain TEXT NOT NULL,
                    path TEXT NOT NULL,
                    edge_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(domain, path),
                    FOREIGN KEY (edge_id) REFERENCES edges(id)
                )
            """)

            # ---- 新增表 ----
            conn.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id INTEGER NOT NULL,
                    content_snap TEXT NOT NULL,
                    paths_snap TEXT NOT NULL,
                    snapped_at TEXT NOT NULL,
                    confirmed_by TEXT NOT NULL DEFAULT '{"ai":false,"user":false}',
                    reason TEXT,
                    FOREIGN KEY (memory_id) REFERENCES memories(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS co_occurrence (
                    memory_id_a INTEGER NOT NULL,
                    memory_id_b INTEGER NOT NULL,
                    count INTEGER NOT NULL DEFAULT 1,
                    last_seen TEXT NOT NULL,
                    PRIMARY KEY (memory_id_a, memory_id_b)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_confirmations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    op_type TEXT NOT NULL,
                    memory_id INTEGER,
                    payload TEXT NOT NULL,
                    ai_ok INTEGER NOT NULL DEFAULT 0,
                    user_ok INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)

            # ---- 向量虚拟表 ----
            try:
                conn.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories "
                    f"USING vec0(embedding float[{EMBEDDING_DIM}])"
                )
            except Exception:
                pass

            # ---- 索引 ----
            for ddl in [
                "CREATE INDEX IF NOT EXISTS idx_edges_disclosure ON edges(disclosure)",
                "CREATE INDEX IF NOT EXISTS idx_memories_node_uuid ON memories(node_uuid)",
                "CREATE INDEX IF NOT EXISTS idx_memories_deprecated ON memories(node_uuid, deprecated)",
                "CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status)",
                "CREATE INDEX IF NOT EXISTS idx_memories_decay ON memories(decay_score)",
                "CREATE INDEX IF NOT EXISTS idx_co_occ_a ON co_occurrence(memory_id_a)",
            ]:
                conn.execute(ddl)

            conn.execute(
                "INSERT OR IGNORE INTO nodes(uuid, created_at) VALUES (?, ?)",
                (CORE_AGENT_NODE_UUID, _now_iso()),
            )

            # 启动时自动补齐新字段（向后兼容旧数据库）
            self._migrate_schema(conn)

    # ── Schema 迁移 ─────────────────────────────────────

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """启动时检查并补上新字段（向后兼容）"""
        cur = conn.cursor()

        # 检查 paths 表是否有 context 字段
        cur.execute("PRAGMA table_info(paths)")
        paths_cols = {row[1] for row in cur.fetchall()}
        if "context" not in paths_cols:
            cur.execute("ALTER TABLE paths ADD COLUMN context TEXT DEFAULT '[]'")
            log.info("[graph_store] paths 表已添加 context 字段")

        # 检查 memories 表是否有 auto_ingested 字段
        cur.execute("PRAGMA table_info(memories)")
        mem_cols = {row[1] for row in cur.fetchall()}
        if "auto_ingested" not in mem_cols:
            cur.execute("ALTER TABLE memories ADD COLUMN auto_ingested INTEGER DEFAULT 0")
            log.info("[graph_store] memories 表已添加 auto_ingested 字段")

        conn.commit()

    # ── 节点 ──────────────────────────────────────────────

    @staticmethod
    def normalize_uri(
        uri_or_path: str, default_domain: str = DEFAULT_DOMAIN
    ) -> Tuple[str, str]:
        raw = (uri_or_path or "").strip()
        if not raw:
            raise ValueError("Empty uri/path")
        if "://" in raw:
            domain, path = raw.split("://", 1)
            domain = domain.strip() or default_domain
            path = path.strip().strip("/")
            if not path:
                raise ValueError(f"Invalid uri: {uri_or_path}")
            return domain, path
        return default_domain, raw.strip().strip("/")

    def uri_for_path(self, domain: str, path: str) -> str:
        return f"{domain}://{path}"

    def ensure_node(self, node_uuid: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO nodes(uuid, created_at) VALUES (?, ?)",
                (node_uuid, _now_iso()),
            )

    # ── 写记忆 ────────────────────────────────────────────

    def create_or_update_memory_version(
        self,
        node_uuid: str,
        content: str,
        summary: str,
        importance: int,
        is_permanent: bool,
        auto_ingested: bool = False,
    ) -> int:
        self.ensure_node(node_uuid)

        # 生成 embedding（失败不阻断主流程）
        embedding_id: Optional[int] = None
        try:
            vec = _embed(f"{summary}\n{content}")
            with self._connect() as conn:
                vec_store = VecStore(conn)
                if vec_store.available:
                    embedding_id = vec_store.insert(conn, vec)
        except Exception as e:
            log.warning(f"embedding 生成失败（不影响存储）：{e}")

        with self._connect() as conn:
            conn.execute(
                "UPDATE memories SET deprecated=1 WHERE node_uuid=? AND deprecated=0",
                (node_uuid,),
            )
            cur = conn.execute(
                """INSERT INTO memories (
                    node_uuid, content, summary, importance, is_permanent,
                    created_at, deprecated, usage_count, last_used,
                    decay_score, access_count, status, embedding_id, auto_ingested
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, NULL, 1.0, 0, 'active', ?, ?)""",
                (
                    node_uuid, content, summary,
                    int(importance), 1 if is_permanent else 0,
                    _now_iso(), embedding_id,
                    1 if auto_ingested else 0,
                ),
            )
            return int(cur.lastrowid)

    def get_active_memory_by_node(
        self, node_uuid: str
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE node_uuid=? AND deprecated=0 "
                "ORDER BY created_at DESC LIMIT 1",
                (node_uuid,),
            ).fetchone()
            return dict(row) if row else None

    # ── 边 & 路径 ──────────────────────────────────────────

    def add_edge(
        self, parent_uuid: str, child_uuid: str, disclosure: str, priority: int = 0
    ) -> int:
        self.ensure_node(parent_uuid)
        self.ensure_node(child_uuid)
        disclosure = (disclosure or "").strip()
        if not disclosure:
            raise ValueError("disclosure empty")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO edges "
                "(parent_uuid, child_uuid, priority, disclosure, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (parent_uuid, child_uuid, int(priority), disclosure, _now_iso()),
            )
            if cur.lastrowid:
                return int(cur.lastrowid)
            row = conn.execute(
                "SELECT id FROM edges WHERE parent_uuid=? AND child_uuid=? AND disclosure=?",
                (parent_uuid, child_uuid, disclosure),
            ).fetchone()
            if not row:
                raise RuntimeError("Failed to create/find edge")
            return int(row["id"])

    def get_edge_id_by_path(self, domain: str, path: str) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT edge_id FROM paths WHERE domain=? AND path=?",
                (domain, path),
            ).fetchone()
            return int(row["edge_id"]) if row else None

    def get_child_uuid_by_edge_id(self, edge_id: int) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT child_uuid FROM edges WHERE id=?", (edge_id,)
            ).fetchone()
            return str(row["child_uuid"]) if row else None

    def add_or_replace_path(
        self, domain: str, path: str, edge_id: int, context: list = None
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO paths(domain, path, edge_id, context, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    domain, path, int(edge_id),
                    json.dumps(context or [], ensure_ascii=False),
                    _now_iso(),
                ),
            )

    # ── 检索（向量 + token 融合） ────────────────────────────

    def fetch_alias_candidates(
        self, query_text: str, max_candidates: int = 25
    ) -> List[Dict[str, Any]]:
        q = (query_text or "").lower()
        q_tokens = {t for t in q.split() if len(t) > 1}

        # ---- 拉取所有 path→edge→memory ----
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT p.domain, p.path, p.edge_id,
                          e.parent_uuid, e.child_uuid,
                          e.priority AS edge_priority, e.disclosure
                   FROM paths p JOIN edges e ON e.id = p.edge_id
                   WHERE p.domain IS NOT NULL"""
            ).fetchall()

            child_uuids = sorted({str(r["child_uuid"]) for r in rows if r["child_uuid"]})
            mem_by_node: Dict[str, Any] = {
                nid: self.get_active_memory_by_node(nid) for nid in child_uuids
            }

            # ---- 向量召回（可选） ----
            vec_scores: Dict[int, float] = {}
            try:
                vec_store = VecStore(conn)
                if vec_store.available:
                    query_vec = _embed(query_text)
                    hits = vec_store.search(conn, query_vec, top_k=max_candidates)
                    # distance → similarity（cosine distance ∈ [0,2]，越小越好）
                    max_dist = max((d for _, d in hits), default=2.0) or 2.0
                    for rowid, dist in hits:
                        vec_scores[rowid] = 1.0 - dist / max_dist
            except Exception as e:
                log.warning(f"向量检索失败，降级：{e}")

            # ---- co_occurrence 加权 ----
            co_scores: Dict[int, float] = {}
            if vec_scores:
                top_ids = list(vec_scores.keys())[:5]
                if top_ids:
                    placeholders = ",".join("?" * len(top_ids))
                    co_rows = conn.execute(
                        f"SELECT memory_id_b, SUM(count) AS total "
                        f"FROM co_occurrence WHERE memory_id_a IN ({placeholders}) "
                        f"GROUP BY memory_id_b",
                        top_ids,
                    ).fetchall()
                    if co_rows:
                        max_co = max(r["total"] for r in co_rows) or 1
                        for r in co_rows:
                            co_scores[r["memory_id_b"]] = r["total"] / max_co

        # ---- 组装候选 ----
        candidates = []
        for r in rows:
            child_uuid = str(r["child_uuid"])
            mem = mem_by_node.get(child_uuid)
            if not mem:
                continue

            disclosure = r["disclosure"] or ""
            summary = mem.get("summary") or ""
            content = mem.get("content") or ""
            mem_id = mem["id"]

            # token 得分
            d_tok = {t for t in disclosure.lower().split() if len(t) > 1}
            s_tok = {t for t in summary.lower().split() if len(t) > 1}
            c_tok = {t for t in content.lower().split() if len(t) > 1}
            token_score = (
                len(q_tokens & d_tok) * 2
                + len(q_tokens & s_tok)
                + len(q_tokens & c_tok)
            )
            max_token = max(
                len(d_tok) * 2 + len(s_tok) + len(c_tok), 1
            )
            token_norm = token_score / max_token

            # 向量得分（按 embedding_id 对应）
            emb_id = mem.get("embedding_id")
            vec_s = vec_scores.get(emb_id, 0.0) if emb_id else 0.0

            # 共现得分
            co_s = co_scores.get(mem_id, 0.0)

            # 衰减修正
            decay = float(mem.get("decay_score") or 1.0)

            # 融合：向量权重 0.5，token 0.3，共现 0.2（冷启动共现趋 0 无影响）
            if vec_scores:
                final_score = (vec_s * 0.5 + token_norm * 0.3 + co_s * 0.2) * decay
            else:
                # 无向量时退回纯 token
                final_score = token_norm * decay

            candidates.append({
                "domain": r["domain"],
                "path": r["path"],
                "uri": self.uri_for_path(r["domain"], r["path"]),
                "edge_id": r["edge_id"],
                "parent_uuid": r["parent_uuid"],
                "child_uuid": child_uuid,
                "disclosure": disclosure,
                "edge_priority": r["edge_priority"],
                "memory_id": mem_id,
                "summary": summary,
                "content": content,
                "importance": mem["importance"],
                "is_permanent": bool(mem["is_permanent"]),
                "created_at": mem["created_at"],
                "base_score": final_score,
            })

        candidates.sort(key=lambda x: x["base_score"], reverse=True)
        return candidates[:max_candidates]

    # ── 使用标记 & 共现 ────────────────────────────────────

    def mark_memory_used(self, memory_id: int, inject_reason: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE memories SET "
                "  usage_count = usage_count + 1, "
                "  access_count = access_count + 1, "
                "  last_used = ? "
                "WHERE id = ? AND deprecated=0",
                (_now_iso(), int(memory_id)),
            )

    def update_co_occurrence(self, memory_ids: List[int]) -> None:
        """把本次一起被召回的记忆对共现 +1"""
        if len(memory_ids) < 2:
            return
        now = _now_iso()
        pairs = [
            (a, b) for i, a in enumerate(memory_ids)
            for b in memory_ids[i + 1:]
        ]
        with self._connect() as conn:
            for a, b in pairs:
                conn.execute(
                    "INSERT INTO co_occurrence(memory_id_a, memory_id_b, count, last_seen) "
                    "VALUES(?,?,1,?) ON CONFLICT(memory_id_a,memory_id_b) "
                    "DO UPDATE SET count=count+1, last_seen=excluded.last_seen",
                    (a, b, now),
                )

    # ── 遗忘曲线（周度批量更新） ────────────────────────────

    def decay_all(self) -> int:
        """
        R = e^(-t/S)
        t = 距上次访问天数
        S = 1 + log(1 + access_count) * (3 if is_permanent else 1)
        返回更新条数
        """
        now = datetime.now(timezone.utc)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, last_used, access_count, is_permanent "
                "FROM memories WHERE deprecated=0 AND status='active'"
            ).fetchall()

            updated = 0
            for row in rows:
                ref_time_str = row["last_used"] or row["last_used"]
                try:
                    if ref_time_str:
                        ref = datetime.fromisoformat(ref_time_str)
                        if ref.tzinfo is None:
                            ref = ref.replace(tzinfo=timezone.utc)
                    else:
                        # 从未被用，用创建时间替代
                        ref = now
                except Exception:
                    ref = now

                t = max(0.0, (now - ref).total_seconds() / 86400)
                access = int(row["access_count"] or 0)
                perm_factor = 3 if row["is_permanent"] else 1
                S = 1 + math.log1p(access) * perm_factor
                decay = math.exp(-t / S)

                conn.execute(
                    "UPDATE memories SET decay_score=? WHERE id=?",
                    (round(decay, 6), row["id"]),
                )
                updated += 1

            return updated

    # ── 快照（修改前调用） ────────────────────────────────

    def snapshot_memory(
        self, memory_id: int, reason: str = ""
    ) -> Optional[int]:
        with self._connect() as conn:
            mem = conn.execute(
                "SELECT * FROM memories WHERE id=?", (memory_id,)
            ).fetchone()
            if not mem:
                return None

            # 找关联 paths
            paths_rows = conn.execute(
                """SELECT p.domain, p.path, e.disclosure
                   FROM paths p JOIN edges e ON e.id=p.edge_id
                   JOIN nodes n ON n.uuid=e.child_uuid
                   JOIN memories m ON m.node_uuid=n.uuid
                   WHERE m.id=? AND m.deprecated=0""",
                (memory_id,),
            ).fetchall()
            paths_snap = json.dumps(
                [dict(r) for r in paths_rows], ensure_ascii=False
            )

            cur = conn.execute(
                "INSERT INTO snapshots"
                "(memory_id, content_snap, paths_snap, snapped_at, reason) "
                "VALUES(?,?,?,?,?)",
                (
                    memory_id,
                    mem["content"],
                    paths_snap,
                    _now_iso(),
                    reason,
                ),
            )
            return int(cur.lastrowid)

    # ── 双确认队列 ────────────────────────────────────────

    def queue_pending(
        self,
        op_type: str,
        payload: Dict[str, Any],
        memory_id: Optional[int] = None,
        ai_ok: bool = True,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO pending_confirmations"
                "(op_type, memory_id, payload, ai_ok, user_ok, created_at) "
                "VALUES(?,?,?,?,0,?)",
                (
                    op_type,
                    memory_id,
                    json.dumps(payload, ensure_ascii=False),
                    1 if ai_ok else 0,
                    _now_iso(),
                ),
            )
            return int(cur.lastrowid)

    def user_confirm(self, pending_id: int) -> bool:
        """用户确认；双方都 ok 后返回 True，由调用方执行真正操作"""
        with self._connect() as conn:
            conn.execute(
                "UPDATE pending_confirmations SET user_ok=1 WHERE id=?",
                (pending_id,),
            )
            row = conn.execute(
                "SELECT ai_ok, user_ok FROM pending_confirmations WHERE id=?",
                (pending_id,),
            ).fetchone()
            if row and row["ai_ok"] and row["user_ok"]:
                return True
        return False

    def list_pending(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pending_confirmations "
                "WHERE user_ok=0 ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
