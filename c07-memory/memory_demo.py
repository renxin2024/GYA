#!/usr/bin/env python3
"""C07 演示：四层记忆——上下文、情节、语义、程序。

跑一遍你能看到：
  1. 情节记忆：会话中提取"我叫张三/我爱喝茶"→ 落 SQLite → 重启读回
  2. 语义记忆：bge-m3 向量化 → Qdrant 检索，跨会话召回偏好；
     同义改写（"爱喝"与"喜欢喝"）也能命中
  3. 无记忆对照：没有上下文时，模型只能回答"我不知道"
  4. 离线兜底：Embedding/Qdrant 没起时，用 TF-IDF 也能跑通检索逻辑

用法:
    export DEEPSEEK_API_KEY=sk-xxx   # LLM 对照用（可选）
    export QDRANT_API_KEY=xxx        # Qdrant 认证（Hermes .env 里有）
    python3 memory_demo.py

依赖: Python 3.10+，仅标准库。真实 Embedding 需 Ollama bge-m3 服务在线。
"""

from __future__ import annotations

import json
import os
import urllib.request

from memory import (
    WorkingMemory,
    EpisodicMemory,
    SemanticMemory,
    OfflineSemanticMemory,
    DB_PATH,
)

# LLM（只做"无记忆 vs 有记忆"的对照，核心机制不依赖它）
LLM_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/chat/completions")
LLM_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")


def call_llm(messages) -> str:
    """调用 LLM 拿一段回答。仅用于对照，不参与记忆机制本身。"""
    payload = {"model": MODEL, "messages": messages, "stream": False}
    req = urllib.request.Request(
        LLM_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {LLM_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]


def section(title: str) -> None:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def demo_episodic() -> None:
    """情节记忆：SQLite 落盘，重启读回。"""
    section("[1] 情节记忆：关键事实落 SQLite，重启读回")
    print("（会话 A：用户自报姓名与偏好，Agent 提取成结构化事实）")
    mem = EpisodicMemory(DB_PATH)
    # 清空旧数据，保证每次演示从干净状态开始
    mem.conn.execute("DELETE FROM facts")
    mem.conn.commit()

    mem.add("用户名", "张三", session_id="session-A")
    mem.add("偏好", "喝茶，尤其是龙井", session_id="session-A")
    mem.add("职业", "Java 后端工程师", session_id="session-A")
    print("\n情节记忆已写入 SQLite（3 条）：")
    print(mem.summary())

    print("\n（模拟进程重启：新开一个 EpisodicMemory 连接，读回）")
    mem.close()
    mem2 = EpisodicMemory(DB_PATH)
    print("重启后读回的事实：")
    for f in mem2.all():
        print(f"  - {f['subject']}: {f['fact']}  (session={f['session_id']})")
    mem2.close()


def demo_semantic() -> None:
    """语义记忆：bge-m3 + Qdrant 检索，含同义改写命中。"""
    section("[2] 语义记忆：bge-m3 + Qdrant，跨会话召回（含同义改写）")

    docs = [
        "用户喜欢喝茶，尤其是龙井",
        "用户职业是 Java 后端工程师，擅长并发编程",
        "用户的博客主题是 AI Agent 开发",
    ]

    try:
        sem = SemanticMemory()
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Embedding/Qdrant 不可达，降级到离线 TF-IDF 检索：{e}")
        sem = OfflineSemanticMemory()

    for d in docs:
        sem.store(d)

    queries = ["用户喜欢喝什么？", "用户爱喝什么饮料？", "用户职业是什么？", "博客写什么？"]
    for q in queries:
        hits = sem.retrieve(q)
        if hits:
            score, text = hits[0]
            print(f"  问「{q}」→ 命中 [{text}]  score={score}")
        else:
            print(f"  问「{q}」→ 无匹配")


def demo_contrast() -> None:
    """无记忆对照：模型没有上下文时答不上来。"""
    section("[3] 无记忆对照：模型没有上下文时，答不上'我是谁'")
    if not LLM_KEY:
        print("  （未设置 DEEPSEEK_API_KEY，跳过 LLM 对照）")
        return
    q = "我是谁？我叫什么名字？（没有任何上下文）"
    reply = call_llm([{"role": "user", "content": q}])
    print(f"  问: {q}")
    print(f"  模型: {reply[:100]}")


def demo_procedural() -> None:
    """程序记忆：只点一句，钩 C09。"""
    section("[4] 程序记忆：事实会过期，方法可复用（钩第九话 Skill）")
    print("  前三层记住的是『事实』；第四层记住的是『怎么做』。")
    print("  把『经过验证的做法』固化成可重复调用的资产，就是 Skill——第九话展开。")


def main() -> int:
    demo_episodic()
    demo_semantic()
    demo_contrast()
    demo_procedural()
    print("\n" + "=" * 64)
    print("核心结论：上下文窗口 ≠ 记忆。")
    print("  模型从不记得任何事，是我们每次把该记住的东西检索出来、塞回给它的。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
