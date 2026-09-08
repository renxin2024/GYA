#!/usr/bin/env python3
"""C07 记忆篇：四层记忆模型。

核心认知：上下文窗口 ≠ 记忆。模型从不记得任何事，是我们每次把该记住的东西
从持久化存储里检索出来、塞回给它的。

四层分工（按「区分依据」划分，存储介质是实现选择，不绑定类型）：
- 工作记忆（Working）    ：当前决策正在使用的信息，内存 messages，最易失
- 情节记忆（Episodic）   ：具体经历及其发生背景（某次对话里用户说想少喝咖啡）
- 语义记忆（Semantic）   ：提炼后的事实/知识/偏好（用户目前倾向少喝咖啡）
- 程序记忆（Procedural） ：完成任务的方法或行为规则（本篇只点一句，钩 C09 Skill）

存储介质是实现选择：本篇情节记忆用 SQLite（标准库 sqlite3）、语义记忆用
Qdrant 向量检索，但情节记忆同样能做向量检索、语义记忆同样能走 SQL 查询。
依赖：Python 3.10+，仅标准库；真实 Embedding 需 Ollama bge-m3 服务。
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone, timedelta

from embedding import embed_one, tfidf_matrix, cosine

# ---------------------------------------------------------------
# 环境配置（Key/地址只从环境变量读，不进代码、不进 Trace）
# ---------------------------------------------------------------
QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "")
COLLECTION = os.environ.get("MEMORY_COLLECTION", "gya_c07_memories")
VECTOR_DIM = int(os.environ.get("MEMORY_VECTOR_DIM", "1024"))
DB_PATH = os.environ.get("MEMORY_DB_PATH", "gya_c07_memory.db")

TZ = timezone(timedelta(hours=8))


# ---------------------------------------------------------------
# 工作记忆（Working）：内存 messages，窗口内
# ---------------------------------------------------------------
class WorkingMemory:
    """窗口内的完整对话历史。模型无状态，全靠它每次喂全。"""

    def __init__(self):
        self.messages: list[dict] = []

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def snapshot(self) -> list[dict]:
        """返回一个浅拷贝，避免调用方误改内部状态。"""
        return list(self.messages)

    def __len__(self) -> int:
        return len(self.messages)


# ---------------------------------------------------------------
# 情节记忆（Episodic）：SQLite 持久化的「经历及其背景」
# ---------------------------------------------------------------
class EpisodicMemory:
    """会话内发生过的具体经历（subject/fact），SQLite 落盘，重启可读回。

    注意：SQLite 是这里选的实现介质，不是「情节记忆」的定义。情节记忆的
    本质是「具体经历及其发生背景」；同样可以用向量库存、用向量检索。
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,      -- 事实主体（如 用户名/偏好/职业）
                fact TEXT NOT NULL,         -- 事实内容
                session_id TEXT NOT NULL,   -- 产生于哪个会话（区分情节 vs 语义）
                created_at TEXT NOT NULL
            )"""
        )
        self.conn.commit()

    def add(self, subject: str, fact: str, session_id: str = "default") -> None:
        now = datetime.now(TZ).isoformat()
        self.conn.execute(
            "INSERT INTO facts(subject, fact, session_id, created_at) VALUES (?,?,?,?)",
            (subject, fact, session_id, now),
        )
        self.conn.commit()

    def all(self) -> list[dict]:
        cur = self.conn.execute(
            "SELECT subject, fact, session_id, created_at FROM facts ORDER BY id"
        )
        return [
            {"subject": r[0], "fact": r[1], "session_id": r[2], "created_at": r[3]}
            for r in cur.fetchall()
        ]

    def summary(self) -> str:
        return "\n".join(f"- {f['subject']}: {f['fact']}" for f in self.all())

    def close(self) -> None:
        self.conn.close()


# ---------------------------------------------------------------
# 语义记忆（Semantic）：跨会话的偏好/知识，向量检索（bge-m3 + Qdrant）
# ---------------------------------------------------------------
class SemanticMemory:
    """跨会话的偏好/知识。核心机制：写入时向量化，检索时算相似度召回。

    "不检索的记忆等于不存在"——这一层的关键不是"存了"，而是"能检索回来"。
    注意：向量检索是这里选的实现方式，不是「语义记忆」的定义；语义记忆
    也能通过 SQL 直接查询（例如按 subject 精确取一条偏好）。
    """

    def __init__(self, url: str = QDRANT_URL, api_key: str = QDRANT_API_KEY):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self._ensure_collection()

    def _headers(self) -> dict:
        return {"api-key": self.api_key} if self.api_key else {}

    def _ensure_collection(self) -> None:
        get = urllib.request.Request(f"{self.url}/collections/{COLLECTION}", headers=self._headers())
        try:
            urllib.request.urlopen(get, timeout=10)
        except Exception:  # noqa: BLE001 — 不存在则创建
            body = {"vectors": {"size": VECTOR_DIM, "distance": "Cosine"}}
            req = urllib.request.Request(
                f"{self.url}/collections/{COLLECTION}",
                data=json.dumps(body).encode(),
                headers={**self._headers(), "Content-Type": "application/json"},
                method="PUT",
            )
            urllib.request.urlopen(req, timeout=10)

    def store(self, text: str, payload: dict | None = None) -> None:
        """把一条记忆向量化后写入 Qdrant。"""
        vector = embed_one(text)
        # Qdrant point id 只接受无符号整数或 UUID；用整数最稳。
        point_id = abs(hash(text)) % (10 ** 12)
        body = {"points": [{"id": point_id, "vector": vector, "payload": payload or {"text": text}}]}
        req = urllib.request.Request(
            f"{self.url}/collections/{COLLECTION}/points?wait=true",
            data=json.dumps(body).encode(),
            headers={**self._headers(), "Content-Type": "application/json"},
            method="PUT",
        )
        urllib.request.urlopen(req, timeout=30)

    def retrieve(self, query: str, top_k: int = 2, min_score: float = 0.0) -> list[tuple[float, str]]:
        """检索与 query 最相似的前 top_k 条记忆，返回 [(score, text)]。

        min_score：相似度阈值，低于它的候选被丢弃。加阈值是为了把「低分噪声」
        和「真正的命中」分开——检索总会返回 top-k 条，但分数太低时不该硬塞给
        模型，而应视为「无命中」。这是「候选怎么筛选」这道工序的最小实现。
        """
        vector = embed_one(query)
        body = {"vector": vector, "limit": top_k, "with_payload": True}
        req = urllib.request.Request(
            f"{self.url}/collections/{COLLECTION}/points/search",
            data=json.dumps(body).encode(),
            headers={**self._headers(), "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        hits = []
        for p in result.get("result", []):
            score = p.get("score", 0.0)
            if score < min_score:
                continue
            text = p.get("payload", {}).get("text", "")
            hits.append((round(score, 3), text))
        return hits


# ---------------------------------------------------------------
# 离线夹具：TF-IDF 检索（语义记忆的"服务不可达"回归版）
# ---------------------------------------------------------------
class OfflineSemanticMemory:
    """纯 Python TF-IDF 检索，用于"Embedding/Qdrant 没起"时的回归。

    它证明的是"检索"这个机制本身（写向量 → 算相似度 → 召回），
    不冒充真实 Embedding 的同义改写能力。
    """

    def __init__(self):
        self.texts: list[str] = []

    def store(self, text: str, payload: dict | None = None) -> None:
        self.texts.append(text)

    def retrieve(self, query: str, top_k: int = 2, min_score: float = 0.0) -> list[tuple[float, str]]:
        docs = self.texts + [query]
        matrix, _ = tfidf_matrix(docs)
        qvec = matrix[-1]
        scored = [(cosine(qvec, matrix[i]), self.texts[i]) for i in range(len(self.texts))]
        scored.sort(reverse=True)
        return [(round(s, 3), t) for s, t in scored[:top_k] if s > 0 and s >= min_score]


# ---------------------------------------------------------------
# 程序记忆（Procedural）：只点一句，钩 C09 Skill
# ---------------------------------------------------------------
# 第四层是「完成任务的方法或行为规则」——它不是「记住了什么事实」，而是
# 「记住了怎么做」。把它固化下来，就是「技能（Skill）」。这是第九话要展开
# 的话题，本篇只立住概念。方法同样可能过时、需要维护，事实也可以被反复
# 复用，所以别用「事实会过期 / 方法可复用」来划这条分界线——真正的区别
# 是：程序记忆记的是「怎么做一件事」，前三层记的是「关于世界与经历的信息」。
