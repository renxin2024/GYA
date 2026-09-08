#!/usr/bin/env python3
"""C07 离线回归测试：不依赖 Embedding/Qdrant/LLM 服务。

只验证"记忆机制本身"的可运行性：
- TF-IDF 兜底能跑通检索逻辑
- 情节记忆 SQLite 落盘 + 读回
- 工作记忆快照隔离

用 unittest 跑：python3 -m unittest test_memory -v
"""

from __future__ import annotations

import os
import tempfile
import unittest

from memory import EpisodicMemory, OfflineSemanticMemory, WorkingMemory
from embedding import tfidf_matrix, cosine


class TestWorkingMemory(unittest.TestCase):
    def test_snapshot_is_copy(self):
        wm = WorkingMemory()
        wm.add("user", "你好")
        snap = wm.snapshot()
        snap.append({"role": "user", "content": "污染"})
        self.assertEqual(len(wm), 1, "snapshot 应该是拷贝，不应影响内部状态")


class TestEpisodicMemory(unittest.TestCase):
    def test_persist_and_readback(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "test.db")
            mem = EpisodicMemory(db)
            mem.add("用户名", "张三", session_id="s1")
            mem.close()

            # 模拟重启：新连接读回
            mem2 = EpisodicMemory(db)
            facts = mem2.all()
            self.assertEqual(len(facts), 1)
            self.assertEqual(facts[0]["subject"], "用户名")
            self.assertEqual(facts[0]["fact"], "张三")
            mem2.close()


class TestOfflineSemanticMemory(unittest.TestCase):
    def test_retrieve_hits_correct_doc(self):
        sem = OfflineSemanticMemory()
        docs = [
            "用户喜欢喝茶，尤其是龙井",
            "用户职业是 Java 后端工程师",
            "用户的博客主题是 AI Agent 开发",
        ]
        for d in docs:
            sem.store(d)
        hits = sem.retrieve("用户职业是什么？")
        self.assertTrue(hits, "应该至少命中一条")
        self.assertIn("职业", hits[0][1], "最相似的应该是职业那条")


class TestTfidf(unittest.TestCase):
    def test_cosine_same_text_is_one(self):
        matrix, _ = tfidf_matrix(["用户喜欢喝茶", "用户喜欢喝茶"])
        self.assertAlmostEqual(cosine(matrix[0], matrix[1]), 1.0, places=6)

    def test_cosine_distinct_text_is_zero(self):
        matrix, _ = tfidf_matrix(["苹果", "香蕉"])
        self.assertAlmostEqual(cosine(matrix[0], matrix[1]), 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
