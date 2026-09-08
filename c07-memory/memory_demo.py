#!/usr/bin/env python3
"""C07 演示：四层记忆——工作、情节、语义、程序。

跑一遍你能看到：
  1. 情节记忆：预设写入"我叫张三/我在戒咖啡"→ 落 SQLite → 重启读回，
     并按 subject / session / 关键词 SQL 精确召回
  2. 语义记忆：bge-m3 向量化 → Qdrant 检索，跨会话召回偏好；
     同义改写（"爱喝"与"喜欢喝"）也能命中
  3. 完整闭环：保存记忆 → 新会话提问 → 检索候选 → 组装上下文 → 模型回答。
     对照三种情况：有记忆能答、无记忆不编造、无命中承认不足
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
    print("（会话 A：用户自报姓名与偏好，这里把事实「预设写入」，落盘）")
    mem = EpisodicMemory(DB_PATH)
    # 清空旧数据，保证每次演示从干净状态开始
    mem.conn.execute("DELETE FROM facts")
    mem.conn.commit()

    mem.add("用户名", "张三", session_id="session-A")
    mem.add("偏好", "最近在戒咖啡，想少喝一点", session_id="session-A")
    mem.add("职业", "Java 后端工程师", session_id="session-A")
    print("\n情节记忆已写入 SQLite（3 条）：")
    print(mem.summary())

    print("\n（模拟进程重启：新开一个 EpisodicMemory 连接，读回）")
    mem.close()
    mem2 = EpisodicMemory(DB_PATH)
    print("重启后读回的事实：")
    for f in mem2.all():
        print(f"  - {f['subject']}: {f['fact']}  (session={f['session_id']})")

    print("\n（情节记忆怎么召回：SQL 精确查询，不靠全量读回）")
    by_subject = mem2.by_subject("偏好")
    print(f"  按 subject 精确查「偏好」→ 命中 {len(by_subject)} 条：")
    for f in by_subject:
        print(f"    - {f['fact']}")
    by_session = mem2.by_session("session-A")
    print(f"  按 session 查「session-A」→ 命中 {len(by_session)} 条（这场对话发生过的所有事）：")
    for f in by_session:
        print(f"    - {f['subject']}: {f['fact']}")
    search = mem2.search("咖啡")
    print(f"  按关键词模糊查「咖啡」→ 命中 {len(search)} 条：")
    for f in search:
        print(f"    - {f['subject']}: {f['fact']}")
    mem2.close()


def demo_semantic() -> None:
    """语义记忆：bge-m3 + Qdrant 检索，含同义改写命中。"""
    section("[2] 语义记忆：bge-m3 + Qdrant，跨会话召回（含同义改写）")

    docs = [
        "用户最近在戒咖啡，想少喝一点",
        "用户职业是 Java 后端工程师，擅长并发编程",
        "用户的博客主题是 AI Agent 开发",
    ]

    # 降级覆盖「写入 + 检索」全程，而不只是初始化：Embedding 服务可能在
    # 初始化后、写入时突然不可达。任何一步失败，都整体回退到离线 TF-IDF。
    sem = None
    try:
        sem = SemanticMemory()
        for d in docs:
            sem.store(d)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Embedding/Qdrant 不可达，降级到离线 TF-IDF 检索：{e}")
        sem = OfflineSemanticMemory()
        for d in docs:
            sem.store(d)

    queries = ["用户喝咖啡吗？", "用户想戒掉什么？", "用户职业是什么？", "博客写什么？"]
    for q in queries:
        try:
            hits = sem.retrieve(q)
        except Exception as e:  # noqa: BLE001 — 检索阶段也可能不可达
            print(f"⚠️  检索失败，本次跳过「{q}」：{e}")
            continue
        if hits:
            score, text = hits[0]
            print(f"  问「{q}」→ 命中 [{text}]  score={score}")
        else:
            print(f"  问「{q}」→ 无匹配")


def build_messages(question: str, hits: list[tuple[float, str]] | None) -> list[dict]:
    """把检索命中的记忆组装进消息。

    命中时，把条目连同相似度写进 system 消息，让模型既知道「有这些相关信息」，
    也看得见「它们来自检索、有分数可循」；没命中时，只发用户问题，不塞任何
    编造的内容。这一步是「检索」与「回答」之间缺的那一截：查到了，还要装进去。
    """
    messages: list[dict] = []
    if hits:
        lines = "\n".join(f"- {text}（相似度 {score:.3f}）" for score, text in hits)
        messages.append({
            "role": "system",
            "content": f"你可以参考下面这些关于当前用户、检索自记忆库的信息：\n{lines}",
        })
    messages.append({"role": "user", "content": question})
    return messages


def demo_retrieval_to_answer() -> None:
    """完整闭环：保存记忆 → 新会话提问 → 检索候选 → 组装上下文 → 调用模型。

    对照三种情况，验证「记忆被选中 → 装进消息 → 影响回答」这条链路：
      1. 有记忆：检索命中偏好，模型能回答，且答案可追溯到命中条目；
      2. 无记忆：不给任何检索结果，模型不能编造用户信息；
      3. 无命中：检索不到相关信息，模型应承认信息不足、而非硬答。

    注意：这里检索到的候选是「预设写入」的记忆（见 demo_semantic），
    并不演示「从对话自动提取关键事实」——那是另一道工序，本篇不展开。
    """
    section("[3] 完整闭环：检索结果 → 组装上下文 → 模型回答")
    if not LLM_KEY:
        print("  （未设置 DEEPSEEK_API_KEY，跳过 LLM 对照）")
        return

    # 复用 demo_semantic 的降级逻辑，拿到一个可用的检索器。
    try:
        sem = SemanticMemory()
    except Exception:  # noqa: BLE001
        sem = OfflineSemanticMemory()

    q = "我最近在戒咖啡，聚餐时该注意什么？"

    # 情况一：有记忆——先检索（带相似度阈值，过滤低分噪声），再装进上下文。
    print(f"  问：{q}")
    hits = sem.retrieve(q, top_k=2, min_score=0.5)
    if not hits:
        print("  ⚠️ 检索无命中（低于阈值），跳过有记忆分支")
    else:
        print(f"  检索命中 {len(hits)} 条，组装进 system 消息：")
        for score, text in hits:
            print(f"    - [{text}]（相似度 {score:.3f}）")
        reply = call_llm(build_messages(q, hits))
        print(f"  模型（有记忆）: {reply[:120]}")

    # 情况二：无记忆——同一问题，不给任何检索结果。
    print(f"\n  问：{q}（不给任何记忆）")
    reply = call_llm(build_messages(q, None))
    print(f"  模型（无记忆）: {reply[:120]}")

    # 情况三：无命中——问一个记忆库里没有的话题，检索分数低于阈值。
    q2 = "我上个月去过的那个地方，叫什么名字？"
    hits2 = sem.retrieve(q2, top_k=2, min_score=0.5)
    print(f"\n  问：{q2}")
    if not hits2:
        print("  （检索无命中（低于阈值），如实告知模型没有相关信息）")
        reply = call_llm(build_messages(q2, None))
        print(f"  模型（无命中）: {reply[:120]}")
    else:
        print("  （意外命中，跳过）")


def demo_procedural() -> None:
    """程序记忆：只点一句，钩 C09。"""
    section("[4] 程序记忆：记「怎么做」，而不是「记了什么事实」（钩第九话 Skill）")
    print("  前三层记住的是「关于世界与经历的信息」；第四层记住的是「怎么做一件事」。")
    print("  把「完成任务的流程/规则」固化下来，就是 Skill——第九话展开。")


def main() -> int:
    demo_episodic()
    demo_semantic()
    demo_retrieval_to_answer()
    demo_procedural()
    print("\n" + "=" * 64)
    print("核心结论：上下文窗口 ≠ 记忆。")
    print("  模型单次调用不会自动记住历史，跨会话的信息需要由应用这层保存、检索、再喂回。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
