#!/usr/bin/env python3
"""C07 记忆篇：四层记忆模型。

核心认知：上下文窗口 ≠ 记忆。模型从不记得任何事，是我们每次把该记住的东西
从持久化存储里检索出来、塞回给它的。

四层分工：
- 工作记忆（Working）    ：窗口内的完整对话，内存 messages，最易失
- 情节记忆（Episodic）   ：会话/任务里发生过的关键事实，SQLite 持久化
- 语义记忆（Semantic）   ：跨会话的偏好/知识，向量检索（bge-m3 + Qdrant）
- 程序记忆（Procedural） ："怎么做事"的方法/流程，本篇只点一句（钩 C09 Skill）

持久化：情节记忆走 SQLite（标准库 sqlite3）；语义记忆走 Qdrant（HTTP）。
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
# 情节记忆（Episodic）：SQLite 持久化的关键事实
# ---------------------------------------------------------------
class EpisodicMemory:
    """会话内提取的关键事实（subject/object），SQLite 落盘，重启可读回。

    与"把整段历史塞进 prompt"的区别：只存结构化条目，省 token、抗干扰。
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
# 语义记忆（Semantic）：bge-m3 + Qdrant 向量检索
# ---------------------------------------------------------------
class SemanticMemory:
    """跨会话的偏好/知识。核心机制：写入时向量化，检索时算相似度召回。

    "不检索的记忆等于不存在"——这一层的关键不是"存了"，而是"能检索回来"。
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

    def retrieve(self, query: str, top_k: int = 2) -> list[tuple[float, str]]:
        """检索与 query 最相似的前 top_k 条记忆，返回 [(score, text)]。"""
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
            text = p.get("payload", {}).get("text", "")
            hits.append((round(p.get("score", 0.0), 3), text))
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

    def retrieve(self, query: str, top_k: int = 2) -> list[tuple[float, str]]:
        docs = self.texts + [query]
        matrix, _ = tfidf_matrix(docs)
        qvec = matrix[-1]
        scored = [(cosine(qvec, matrix[i]), self.texts[i]) for i in range(len(self.texts))]
        scored.sort(reverse=True)
        return [(round(s, 3), t) for s, t in scored[:top_k] if s > 0]


# ---------------------------------------------------------------
# 程序记忆（Procedural）：只点一句，钩 C09 Skill
# ---------------------------------------------------------------
# 第四层是"怎么做事的流程/方法"——它不是"记住了什么事实"，而是"记住了怎么做"。
# 把它固化下来，就是"技能（Skill）"。这是第九话要展开的话题，本篇只立住概念：
# 事实会过期，方法可复用；程序记忆把"经过验证的做法"变成可重复调用的资产。
