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
from memory_demo import build_messages


class TestWorkingMemory(unittest.TestCase):
    def test_snapshot_is_copy(self):
        wm = WorkingMemory()
        wm.add("user", "你好")
        snap = wm.snapshot()
        snap.append({"role": "user", "content": "污染"})
        self.assertEqual(len(wm), 1, "snapshot 应该是拷贝，不应影响内部状态")


class TestBuildMessages(unittest.TestCase):
    """闭环组装逻辑：检索命中 → system 消息；无命中 → 只发用户问题。"""

    def test_hits_go_into_system_message(self):
        hits = [(0.753, "用户最近在戒咖啡，想少喝一点")]
        msgs = build_messages("我最近在戒咖啡，聚餐该注意什么？", hits)
        self.assertEqual(msgs[0]["role"], "system", "命中条目应放进 system 消息")
        self.assertIn("戒咖啡", msgs[0]["content"], "system 消息应包含命中记忆内容")
        self.assertEqual(msgs[-1]["role"], "user", "最后一条应是用户问题")

    def test_no_hits_means_no_fabrication(self):
        msgs = build_messages("我上个月去了哪？", None)
        self.assertEqual(len(msgs), 1, "无命中时只发用户问题，不塞编造内容")
        self.assertEqual(msgs[0]["role"], "user")


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

    def test_recall_by_subject(self):
        with tempfile.TemporaryDirectory() as d:
            mem = EpisodicMemory(os.path.join(d, "test.db"))
            mem.add("偏好", "最近在戒咖啡", session_id="s1")
            mem.add("职业", "Java 后端工程师", session_id="s1")
            hits = mem.by_subject("偏好")
            self.assertEqual(len(hits), 1, "按 subject 精确查应只命中偏好")
            self.assertEqual(hits[0]["fact"], "最近在戒咖啡")
            mem.close()

    def test_recall_by_session(self):
        with tempfile.TemporaryDirectory() as d:
            mem = EpisodicMemory(os.path.join(d, "test.db"))
            mem.add("偏好", "最近在戒咖啡", session_id="s1")
            mem.add("职业", "Java 后端工程师", session_id="s2")
            hits = mem.by_session("s1")
            self.assertEqual(len(hits), 1, "按 session 查应只命中 s1 那场对话")
            self.assertEqual(hits[0]["fact"], "最近在戒咖啡")
            mem.close()

    def test_search_by_keyword(self):
        with tempfile.TemporaryDirectory() as d:
            mem = EpisodicMemory(os.path.join(d, "test.db"))
            mem.add("偏好", "最近在戒咖啡", session_id="s1")
            mem.add("职业", "Java 后端工程师", session_id="s1")
            hits = mem.search("咖啡")
            self.assertEqual(len(hits), 1, "关键词「咖啡」应命中偏好那条")
            self.assertEqual(hits[0]["subject"], "偏好")
            mem.close()


class TestOfflineSemanticMemory(unittest.TestCase):
    def test_retrieve_hits_correct_doc(self):
        sem = OfflineSemanticMemory()
        docs = [
            "用户最近在戒咖啡，想少喝一点",
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
