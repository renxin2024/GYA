#!/usr/bin/env python3
"""C02 演示：Function Calling 第一性原理

模型并没有"学会"调用工具——它只是输出了一个 JSON 格式的工具调用请求，
真正执行函数的是调用方（也就是本脚本）的代码。

用法:
    export DEEPSEEK_API_KEY=sk-xxx
    python3 main.py

依赖: Python 3.10+，仅标准库（urllib），无需安装任何包。
"""

import json
import os
import urllib.request

API_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/chat/completions")
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

# ---------------------------------------------------------------
# 1. 我们声明模型"可以用"哪些工具。（声明 ≠ 执行）
# ---------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询指定城市的当前天气。城市例：北京、上海、深圳",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名"}
                },
                "required": ["city"],
            },
        },
    }
]

# 模拟的工具返回数据（真实系统里这里会去请求天气 API）
FAKE_WEATHER = {
    "北京": "多云，25℃，东北风 3 级",
    "上海": "阵雨，28℃，东南风 2 级",
    "深圳": "晴，31℃，南风 2 级",
}


def get_weather(city: str) -> str:
    """真正执行工具的函数——它才是"会干活"的那一方。模型只是说"我想查"，
    这个函数真的去查（这里简化成查一张本地表）。"""
    return FAKE_WEATHER.get(city, f"暂无 {city} 的天气数据")


def call(messages, tools=None):
    """向模型发一次请求。"""
    payload = {"model": MODEL, "messages": messages, "tools": tools, "stream": False}
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def run_tool(name: str, args_str: str):
    """调用方根据模型返回的工具名，分发给对应的真实函数并执行。"""
    args = json.loads(args_str)
    if name == "get_weather":
        return get_weather(args["city"])
    raise ValueError(f"未知工具: {name}")


def main() -> int:
    if not API_KEY:
        print("请先设置 DEEPSEEK_API_KEY 环境变量（https://platform.deepseek.com 获取）")
        return 1

    question = "北京现在天气怎么样？"
    print(f"模型: {MODEL}\n问题: {question}\n" + "-" * 46)

    # 第一轮：把问题 + 工具声明一起发给模型
    messages = [{"role": "user", "content": question}]
    r = call(messages, tools=TOOLS)
    msg = r["choices"][0]["message"]

    if msg.get("tool_calls"):
        # 模型说："我想调用 get_weather(北京)" —— 注意它只说了，没做
        for tc in msg["tool_calls"]:
            fn = tc["function"]
            print(f"[模型说] 我要调用工具: {fn['name']}({fn['arguments']})")
            # 现在调用方（我们的代码）真正执行
            result = run_tool(fn["name"], fn["arguments"])
            print(f"[调用方] 我已执行工具，结果是: {result}")
            # 把工具结果作为一条 role=tool 的消息回喂给模型
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": msg["tool_calls"],
            })
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})

        # 第二轮：模型拿到工具结果，生成最终回答
        r2 = call(messages)
        print(f"[模型最后说] {r2['choices'][0]['message']['content']}")
    else:
        print(f"[模型直接回答] {msg['content']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
