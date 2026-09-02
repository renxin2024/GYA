#!/usr/bin/env python3
"""GYA C02：用一条正常路径跑通 Function Calling。"""

from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI


MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询指定城市的天气演示数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名，如北京"}
                },
                "required": ["city"],
                "additionalProperties": False,
            },
        },
    }
]


def get_weather(city: str) -> str:
    """返回确定性的演示数据；生产环境可替换成真实天气 API。"""
    weather = {
        "北京": "多云，25℃，东北风3级",
        "上海": "小雨，22℃，东南风2级",
    }
    return weather.get(city, f"暂无{city}的天气演示数据")


def execute_tool(name: str, arguments_json: str) -> str:
    """校验模型请求后，再把允许的工具名映射到本地函数。"""
    if name != "get_weather":
        raise ValueError(f"不允许执行未知工具：{name}")

    arguments = json.loads(arguments_json)
    if not isinstance(arguments, dict) or set(arguments) != {"city"}:
        raise ValueError("get_weather 参数必须且只能包含 city")

    city = arguments["city"]
    if not isinstance(city, str) or not city.strip():
        raise ValueError("city 必须是非空字符串")

    return get_weather(city.strip())


def main() -> None:
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("请先设置 LLM_API_KEY 或 DEEPSEEK_API_KEY")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    messages: list[Any] = [
        {"role": "user", "content": "请查询北京现在的天气。"}
    ]

    # 第一次请求：模型只生成结构化工具请求，不执行 Python 函数。
    assistant_message = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=TOOLS,
        tool_choice="required",
        extra_body={"thinking": {"type": "disabled"}},
    ).choices[0].message

    if not assistant_message.tool_calls:
        raise RuntimeError("模型没有返回 tool_calls")
    if len(assistant_message.tool_calls) != 1:
        raise RuntimeError("本示例只处理一个 tool_call")

    tool_call = assistant_message.tool_calls[0]
    print(f"模型请求：{tool_call.function.name}({tool_call.function.arguments})")

    # 真正执行发生在这里：Python 程序调用本地函数。
    result = execute_tool(tool_call.function.name, tool_call.function.arguments)
    print(f"程序执行：{result}")

    # 把模型的调用请求和对应结果一起放回消息历史。
    messages.append(assistant_message)
    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result,
        }
    )

    # 第二次请求：让模型基于工具结果组织面向用户的回答。
    final_message = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=TOOLS,
        tool_choice="none",
        extra_body={"thinking": {"type": "disabled"}},
    ).choices[0].message
    print(f"模型回答：{final_message.content}")


if __name__ == "__main__":
    main()
