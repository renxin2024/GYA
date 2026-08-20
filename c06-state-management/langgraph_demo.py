#!/usr/bin/env python3
"""C06 LangGraph 版：同一个任务用 StateGraph 表达（对照手写版 state_machine.py）。

手写版的三件事——State（dict）/ Node（函数）/ Edge（路由表）——
在 LangGraph 里变成声明式 API：
  - State      → TypedDict（定义共享状态的结构）
  - Node       → add_node("name", func)（函数签名与手写版一致）
  - Edge       → add_edge / add_conditional_edges（确定性路由，不走 LLM）

安装 LangGraph:
    uv run --with langgraph python3 langgraph_demo.py
    或
    pip install langgraph

用法:
    export DEEPSEEK_API_KEY=sk-xxx
    python3 langgraph_demo.py

依赖: Python 3.10+ + langgraph（唯一一个需要第三方库的系列演示）。
"""

import json
import os
import urllib.request
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph

API_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/chat/completions")
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

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
# 1. State：用 TypedDict 声明共享状态结构（LangGraph 会校验/合并字段）
# ---------------------------------------------------------------
class AgentState(TypedDict):
    question: str
    messages: list
    results: dict
    intent: list
    next_step: str
    final_answer: str


# ---------------------------------------------------------------
# 2. Node：函数签名与手写版完全一致（输入 State → 返回要更新的字段）
# ---------------------------------------------------------------
def parse_intent(state: AgentState) -> dict:
    sys = ("你是意图解析器。判断用户问题需要哪些工具，只输出 JSON 列表，"
           "如 [\"get_weather\", \"calculator\"]，不需要其他内容。")
    msg = call_llm([{"role": "system", "content": sys},
                    {"role": "user", "content": state["question"]}])
    try:
        intent = json.loads(msg["content"] or "[]")
    except json.JSONDecodeError:
        intent = []
    print(f"[Node: parse_intent] intent={intent}")
    return {"intent": intent}


def execute_tools(state: AgentState) -> dict:
    messages = state["messages"]
    results = dict(state["results"])
    if state["intent"]:
        msg = call_llm(messages, tools=TOOLS)
        messages.append(msg)
        for tc in msg.get("tool_calls") or []:
            fn = tc["function"]
            args = json.loads(fn["arguments"] or "{}")
            if fn["name"] == "get_weather":
                result = get_weather(args["city"])
            elif fn["name"] == "calculator":
                result = calculator(args["expression"])
            else:
                result = f"未知工具: {fn['name']}"
            results[fn["name"]] = result
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            print(f"[Node: execute_tools] {fn['name']} → {result}")
    return {"messages": messages, "results": results}


def summarize(state: AgentState) -> dict:
    msg = call_llm(state["messages"])
    print(f"[Node: summarize] {msg['content'][:80]}...")
    return {"final_answer": msg["content"]}


# ---------------------------------------------------------------
# 3. Edge：条件路由（确定性代码，不走 LLM）
# ---------------------------------------------------------------
def route_after_tools(state: AgentState) -> str:
    # 有工具结果 → 总结；没有（纯文本意图）→ 直接总结也一样
    return "summarize"


def build_graph():
    g = StateGraph(AgentState)

    # 注册节点
    g.add_node("parse_intent", parse_intent)
    g.add_node("execute_tools", execute_tools)
    g.add_node("summarize", summarize)

    # 定义边
    g.set_entry_point("parse_intent")
    g.add_edge("parse_intent", "execute_tools")
    g.add_conditional_edges("execute_tools", route_after_tools, {"summarize": "summarize"})
    g.add_edge("summarize", END)

    return g.compile()


def main() -> int:
    if not API_KEY:
        print("请先设置 DEEPSEEK_API_KEY 环境变量")
        return 1
    q = "北京天气怎么样？顺便算一下 123*456，最后把两个答案整理成一句话。"
    graph = build_graph()
    result = graph.invoke({
        "question": q,
        "messages": [{"role": "user", "content": q}],
        "results": {},
        "intent": [],
        "next_step": "parse_intent",
        "final_answer": "",
    })
    print("\n" + "=" * 60)
    print("最终答案:", result["final_answer"])
    print("执行轨迹: intent=%s results=%s" % (result["intent"], result["results"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
