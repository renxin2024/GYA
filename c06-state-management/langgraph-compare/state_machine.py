#!/usr/bin/env python3
"""C06 手写状态机版：显式状态 + 节点路由（不依赖任何框架）。

对比 LangGraph 版（langgraph_demo.py）——两者跑同一个任务：
  "北京天气怎么样？顺便算一下 123*456，最后把两个答案整理成一句话。"

手写版的核心：
  - State = 显式 dict（intent / results / next_step / messages）
  - Node  = 一个函数：读 State，做事，返回要更新的字段
  - Edge  = 循环里根据 next_step 路由（确定性代码，不走 LLM）

这正是 StateGraph 的雏形：状态显式化、路由确定性、LLM 只在需要语义的节点被调用。

用法:
    export DEEPSEEK_API_KEY=sk-xxx
    python3 state_machine.py

依赖: Python 3.10+，仅标准库（urllib）。
"""

import json
import os
import urllib.request

API_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/chat/completions")
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

# ---------------------------------------------------------------
# 工具（复用 C04/C05 简化版）
# ---------------------------------------------------------------
FAKE_WEATHER = {
    "北京": "多云，25℃，东北风 3 级",
    "上海": "阵雨，28℃，东南风 2 级",
    "深圳": "晴，31℃，南风 2 级",
}

TOOLS = [
    {"type": "function", "function": {"name": "get_weather",
        "description": "查询指定城市的当前天气。城市例：北京、上海、深圳",
        "parameters": {"type": "object",
                       "properties": {"city": {"type": "string", "description": "城市名"}},
                       "required": ["city"]}}},
    {"type": "function", "function": {"name": "calculator",
        "description": "执行算术表达式计算。例如：123*456、 (1+2)*3",
        "parameters": {"type": "object",
                       "properties": {"expression": {"type": "string", "description": "算术表达式"}},
                       "required": ["expression"]}}},
]


def get_weather(city: str) -> str:
    return FAKE_WEATHER.get(city, f"暂无 {city} 的天气数据")


def calculator(expression: str) -> str:
    allowed = set("0123456789+-*/(). ")
    if not all(c in allowed for c in expression):
        raise ValueError("表达式包含非法字符")
    return str(eval(expression))  # noqa: S307 — 演示用


def call_llm(messages, tools=None):
    payload = {"model": MODEL, "messages": messages, "tools": tools, "stream": False}
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["choices"][0]["message"]


# ---------------------------------------------------------------
# 状态机：State（共享 dict）+ Node（函数）+ Edge（路由）
# ---------------------------------------------------------------
class StateMachine:
    def __init__(self, question: str):
        # State：显式共享状态
        self.state = {
            "question": question,
            "messages": [{"role": "user", "content": question}],
            "results": {},        # 工具结果 {"get_weather": "...", "calculator": "..."}
            "intent": "",         # 语义理解结果
            "next_step": "parse_intent",   # 路由起点
        }

    # ---- Node 1: 语义理解（唯一需要 LLM 的节点）----
    def parse_intent(self):
        sys = ("你是意图解析器。判断用户问题需要哪些工具，只输出 JSON 列表，"
               "如 [\"get_weather\", \"calculator\"]，不需要其他内容。")
        msg = call_llm([{"role": "system", "content": sys}, {"role": "user", "content": self.state["question"]}])
        raw = msg["content"] or "[]"
        try:
            intent = json.loads(raw)
        except json.JSONDecodeError:
            intent = []
        self.state["intent"] = intent
        self.state["next_step"] = "execute_tools"

    # ---- Node 2: 确定性路由 + 执行工具（纯代码，零 token）----
    def execute_tools(self):
        intent = self.state["intent"]
        messages = self.state["messages"]

        # 让模型决定工具参数（LLM 节点）
        if intent:
            msg = call_llm(messages, tools=TOOLS)
            messages.append(msg)   # 原样回传（含 reasoning_content）
            for tc in msg.get("tool_calls") or []:
                fn = tc["function"]
                args = json.loads(fn["arguments"] or "{}")
                if fn["name"] == "get_weather":
                    result = get_weather(args["city"])
                elif fn["name"] == "calculator":
                    result = calculator(args["expression"])
                else:
                    result = f"未知工具: {fn['name']}"
                self.state["results"][fn["name"]] = result
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})

        self.state["next_step"] = "summarize"

    # ---- Node 3: 总结（LLM 节点）----
    def summarize(self):
        msg = call_llm(self.state["messages"])
        self.state["final_answer"] = msg["content"]
        self.state["next_step"] = "END"

    # ---- 路由表（Edge）：确定性跳转，不走 LLM ----
    def run(self, max_steps: int = 10):
        steps = 0
        while self.state["next_step"] != "END" and steps < max_steps:
            node = self.state["next_step"]
            print(f"\n=== Node: {node} ===")
            getattr(self, node)()     # 按 next_step 路由到节点函数
            steps += 1
        return self.state


def main() -> int:
    if not API_KEY:
        print("请先设置 DEEPSEEK_API_KEY 环境变量")
        return 1
    q = "北京天气怎么样？顺便算一下 123*456，最后把两个答案整理成一句话。"
    sm = StateMachine(q)
    state = sm.run()
    print("\n" + "=" * 60)
    print("最终答案:", state.get("final_answer"))
    print("执行轨迹: intent=%s results=%s" % (state["intent"], state["results"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
