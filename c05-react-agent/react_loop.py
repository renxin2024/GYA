#!/usr/bin/env python3
"""C05 react_loop.py：ReAct 主循环（Agent 的核心引擎）。

所有 Agent 框架的本质：
    while 未终止:
        LLM(问题 + 历史) → Thought + Action
        执行 Action → Observation
        追加到历史，继续

模型负责"想"（reasoning_content = Thought，tool_calls = Action），
代码负责"做"（注册表执行工具）+"看"（Observation 回喂）。
"""

import json
import os
import urllib.request
from typing import Dict, List

from state import AgentState, StepRecord
from tools import ToolRegistry, ToolResponse

API_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/chat/completions")
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")


def call_llm(messages: List[Dict], tools=None) -> Dict:
    """调用 LLM，返回 message 对象。"""
    payload = {"model": MODEL, "messages": messages, "tools": tools, "stream": False}
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]


class ReactAgent:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def run(self, question: str, max_steps: int = 6, verbose: bool = True) -> AgentState:
        state = AgentState(question=question, max_steps=max_steps)
        state.add_message({"role": "user", "content": question})

        for step in range(1, max_steps + 1):
            if verbose:
                print(f"\n=== Step {step} ===")

            # 1. 让模型"想"：带着完整历史，决定下一步动作
            msg = call_llm(state.messages, tools=self.registry.list_schemas())
            thought = msg.get("reasoning_content") or ""
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                # 2a. 模型不再需要工具 → 这就是最终答案
                state.final_answer = msg.get("content") or ""
                state.done = True
                if verbose:
                    print(f"[Thought] {thought[:120]}")
                    print(f"[Final Answer] {state.final_answer}")
                break

            # 2b. 模型要调用工具 → 原样回传 assistant 消息（含 reasoning_content）
            state.add_message(msg)
            actions_desc = []
            for tc in tool_calls:
                fn = tc["function"]
                args = json.loads(fn["arguments"] or "{}")
                desc = f"{fn['name']}({json.dumps(args, ensure_ascii=False)})"
                actions_desc.append(desc)
                if verbose:
                    print(f"[Thought] {thought[:120]}")
                    print(f"[Action] 调用 {desc}")

                # 3. 执行工具 → Observation
                resp: ToolResponse = self.registry.execute(fn["name"], args)
                if verbose:
                    print(f"[Observation] {resp.text[:100]}")

                state.add_message({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": resp.text,
                })
                state.record(StepRecord(
                    step=step,
                    thought=thought,
                    action=desc,
                    observation=resp.text,
                ))

        if not state.done:
            state.final_answer = "（达到最大步数仍未完成，已终止）"
        return state
