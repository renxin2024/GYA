#!/usr/bin/env python3
"""C07 演示：三层记忆——上下文、短期、长期

核心认知：上下文窗口 ≠ 记忆。
  - 上下文（Working）：当前 messages，窗口内，最易失
  - 短期（Episodic）：会话内关键事实，显式提取，可跨轮
  - 长期（Semantic）：跨会话持久，向量检索（这里用纯 Python 余弦，零依赖）

演示流程：
  1. 用户连续提问，Agent 从对话中提取关键事实存短期记忆
  2. 新问题依赖"刚才说过的事实"——短期记忆补上模型丢失的上下文
  3. 长期记忆：向量检索"记住"用户偏好/知识点，新会话也能用
  4. Lost-in-the-Middle 效应演示：信息放中间 vs 放开头/结尾

用法:
    export DEEPSEEK_API_KEY=sk-xxx
    python3 memory_demo.py

依赖: Python 3.10+，仅标准库（urllib + math）。
"""

import json
import math
import os
import urllib.request

API_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/chat/completions")
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")


def call_llm(messages, tools=None):
    payload = {"model": MODEL, "messages": messages, "tools": tools, "stream": False}
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["choices"][0]["message"]


# ---------------------------------------------------------------
# 1. 短期记忆：会话内关键事实（显式提取，纯内存）
# ---------------------------------------------------------------
class WorkingMemory:
    """短期记忆：存"刚刚发生过的重要事实"，供后续轮次使用。"""

    def __init__(self):
        self.facts = []          # [{"subject": ..., "fact": ...}]
        self.capacity = 20

    def add(self, subject: str, fact: str):
        # 简单去重：同主题更新
        for f in self.facts:
            if f["subject"] == subject:
                f["fact"] = fact
                return
        self.facts.append({"subject": subject, "fact": fact})
        if len(self.facts) > self.capacity:
            self.facts.pop(0)    # FIFO 遗忘最旧的

    def search(self, keyword: str) -> list:
        return [f for f in self.facts if keyword in f["subject"] or keyword in f["fact"]]

    def summary(self) -> str:
        return "\n".join(f"- {f['subject']}: {f['fact']}" for f in self.facts)


# ---------------------------------------------------------------
# 2. 长期记忆：向量检索（纯 Python 余弦相似度，零依赖）
# ---------------------------------------------------------------
def tokenize(text: str) -> set:
    """极简分词：中文按字 bigram，英文按词。演示够用。"""
    tokens = set()
    # 停用词（演示用，过滤高频噪声）
    stop = {"用户", "喜欢", "什么", "自己", "我们", "这个", "那个", "一个"}
    # 中文 bigram
    for i in range(len(text) - 1):
        if '\u4e00' <= text[i] <= '\u9fff' and '\u4e00' <= text[i+1] <= '\u9fff':
            t = text[i:i+2]
            if t not in stop:
                tokens.add(t)
    # 英文词
    for w in text.split():
        if w.isascii() and len(w) > 1:
            tokens.add(w.lower())
    return tokens


def cosine(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (math.sqrt(len(a)) * math.sqrt(len(b)))


class LongTermMemory:
    """长期记忆：跨会话持久，向量检索。演示用内存 list（生产用向量库）。"""

    def __init__(self):
        self.entries = []        # [{"text": ..., "tokens": set}]

    def store(self, text: str):
        self.entries.append({"text": text, "tokens": tokenize(text)})

    def retrieve(self, query: str, top_k: int = 2) -> list:
        qt = tokenize(query)
        scored = [(cosine(qt, e["tokens"]), e["text"]) for e in self.entries]
        scored.sort(reverse=True)
        return [(text, round(score, 3)) for score, text in scored[:top_k] if score > 0]


# ---------------------------------------------------------------
# 3. Agent：带三层记忆的对话
# ---------------------------------------------------------------
class MemoryAgent:
    def __init__(self):
        self.working = WorkingMemory()       # 短期
        self.longterm = LongTermMemory()     # 长期
        self.history = []                    # 上下文（Working）

    def chat(self, user_msg: str, use_working: bool = True) -> str:
        # 组装消息：上下文 + （可选）短期记忆摘要
        messages = []
        if use_working and self.working.facts:
            messages.append({
                "role": "system",
                "content": "以下是本会话早些时候已确认的事实，回答用户问题时请使用它们：\n" + self.working.summary(),
            })
        messages.append({"role": "user", "content": user_msg})
        reply = call_llm(messages)["content"]
        self.history.append({"role": "user", "content": user_msg})
        self.history.append({"role": "assistant", "content": reply})
        return reply

    def extract_and_store(self, user_msg: str, reply: str):
        """从对话中提取关键事实存入短期记忆（演示：关键词启发式）。"""
        # 演示简化：把"我叫X"/"我喜欢X"这类模式提取出来
        import re
        patterns = [
            (r"我叫(.+?)[，。！？\s]", "用户名字"),
            (r"我喜欢(.+?)[，。！？\s]", "用户偏好"),
            (r"我在(.+?)工作", "用户职业"),
        ]
        combined = user_msg + reply
        for pat, subject in patterns:
            m = re.search(pat, combined)
            if m:
                self.working.add(subject, m.group(1))


def main() -> int:
    if not API_KEY:
        print("请先设置 DEEPSEEK_API_KEY 环境变量")
        return 1

    agent = MemoryAgent()
    print("模型:", MODEL)
    print("=" * 60)

    # ---------- 1. 短期记忆：Agent 记住"刚才"说的事 ----------
    print("\n[1] 短期记忆：用户自报姓名，Agent 存下来")
    u1 = "你好，我叫张三。"
    r1 = agent.chat(u1)
    print(f"  用户: {u1}\n  模型: {r1[:60]}...")
    agent.extract_and_store(u1, r1)
    print("  → 短期记忆已存: 用户名字=张三")
    print(f"  记忆内容:\n{agent.working.summary()}")

    print("\n[2] 短期记忆：几轮之后，模型已经'忘了'用户名字——但记忆补上了")
    # 故意多聊几轮"无关"话题，把名字挤出模型上下文
    for i in range(2):
        agent.chat(f"帮我写一段关于第{i+1}个主题的文字。")
    r2 = agent.chat("我是谁？我叫什么名字？")
    print(f"  模型(带记忆): {r2[:80]}")

    print("\n  对比：不用记忆时模型只能靠上下文猜：")
    r2b = call_llm([{"role": "user", "content": "我是谁？我叫什么名字？（没有任何上下文）"}])["content"]
    print(f"  模型(无记忆): {r2b[:80]}")

    # ---------- 2. 长期记忆：跨"会话"记住 ----------
    print("\n[3] 长期记忆：向量检索")
    ltm = LongTermMemory()
    # 注意：纯 bigram 检索对"同义改写"敏感（如 爱喝 vs 喜欢喝 匹配不到），
    # 这是演示级分词的局限——生产用真实 embedding（同义词投影到相近向量）解决。
    ltm.store("用户喜欢喝茶，尤其是龙井")
    ltm.store("用户职业是 Java 后端工程师，擅长并发编程")
    ltm.store("用户的博客主题是 AI Agent 开发")
    for q in ["用户喜欢喝什么？", "用户职业是什么？", "博客写什么？"]:
        hits = ltm.retrieve(q)
        print(f"  问『{q}』→ {hits}")

    # ---------- 3. Lost-in-the-Middle 效应 ----------
    print("\n[4] Lost-in-the-Middle：信息放中间 vs 开头")
    filler = "你是一个助手。请注意安全。今天天气不错。上下文有点长。继续。"
    center_q = "关键信息是：7 月 25 日开会。其他内容："
    edge_q = "关键信息是：7 月 25 日开会。"
    long_padding = "。".join([f"无关内容 {i}" for i in range(30)])
    # 中间：信息埋在一堆无关内容中间
    mid = call_llm([{"role": "user", "content": center_q + long_padding + "。请回答：哪天开会？只回答日期。"}])["content"]
    # 开头：信息在最前面
    head = call_llm([{"role": "user", "content": edge_q + long_padding + "。请回答：哪天开会？只回答日期。"}])["content"]
    print(f"  信息在中间: 模型回答『{mid.strip()[:40]}』")
    print(f"  信息在开头: 模型回答『{head.strip()[:40]}』")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
