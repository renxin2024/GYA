#!/usr/bin/env python3
"""GYA C01：比较普通聊天与提示词驱动的动作请求。"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI


MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")
QUESTION = "请查询北京现在的天气。如果没有外部数据，请不要猜测。"

ACTION_PROMPT = """
你是动作请求生成器，不要直接回答用户问题。

可用动作：
- get_weather(city: string)：查询指定城市的天气。

当用户的问题需要查询天气时，只输出一行 JSON，不要输出 Markdown、解释或代码围栏：
{"name":"get_weather","arguments":{"city":"城市名"}}

不得使用未列出的动作，不得添加未声明的参数。
""".strip()


@dataclass(frozen=True)
class ActionRequest:
    name: str
    city: str


def api_base_url() -> str:
    """兼容填写 API 根地址或完整 chat/completions 地址的环境变量。"""
    value = os.environ.get("LLM_API_URL", "https://api.deepseek.com").rstrip("/")
    suffix = "/chat/completions"
    if value.endswith(suffix):
        value = value[: -len(suffix)]
    return value


def get_weather(city: str) -> str:
    """返回确定性的演示数据；生产环境可替换成真实天气 API。"""
    weather = {
        "北京": "多云，25℃，东北风3级",
        "上海": "小雨，22℃，东南风2级",
    }
    return weather.get(city, f"暂无{city}的天气演示数据")


def parse_action(text: str) -> ActionRequest:
    """把模型的普通文本输出当作约定 JSON 解析，并执行最小校验。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("模型没有返回合法的纯 JSON") from exc

    if not isinstance(data, dict) or set(data) != {"name", "arguments"}:
        raise ValueError("动作请求必须且只能包含 name 和 arguments")
    if data["name"] != "get_weather":
        raise ValueError(f"不允许执行未知动作：{data['name']}")

    arguments = data["arguments"]
    if not isinstance(arguments, dict) or set(arguments) != {"city"}:
        raise ValueError("get_weather 参数必须且只能包含 city")
    city = arguments["city"]
    if not isinstance(city, str) or not city.strip():
        raise ValueError("city 必须是非空字符串")
    return ActionRequest(name="get_weather", city=city.strip())


def execute_action(action: ActionRequest) -> str:
    """真正的动作发生在 Python 分支，而不是模型响应内部。"""
    if action.name != "get_weather":
        raise ValueError(f"不允许执行未知动作：{action.name}")
    return get_weather(action.city)


def request_text(client: OpenAI, messages: list[dict[str, str]]) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0,
        extra_body={"thinking": {"type": "disabled"}},
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("模型没有返回文本内容")
    return content.strip()


def run_chat(client: OpenAI) -> None:
    """普通聊天：响应只被打印，不会进入任何工具执行分支。"""
    answer = request_text(client, [{"role": "user", "content": QUESTION}])
    print(f"普通聊天输出：{answer}")
    print("Python 执行动作：否")


def run_prompt_tool(client: OpenAI) -> None:
    """提示词协议：把模型文本解释为动作请求，再由 Python 执行。"""
    action_text = request_text(
        client,
        [
            {"role": "system", "content": ACTION_PROMPT},
            {"role": "user", "content": QUESTION},
        ],
    )
    print(f"模型输出动作文本：{action_text}")
    action = parse_action(action_text)
    result = execute_action(action)
    print(f"Python 执行动作：{action.name}({json.dumps({'city': action.city}, ensure_ascii=False)})")
    print(f"工具返回：{result}")


def build_client() -> OpenAI:
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("请先设置 LLM_API_KEY 或 DEEPSEEK_API_KEY")
    return OpenAI(api_key=api_key, base_url=api_base_url())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("chat", "prompt-tool", "all"),
        default="all",
        help="运行普通聊天、提示词动作协议，或依次运行两者",
    )
    args = parser.parse_args()
    client = build_client()

    if args.mode in ("chat", "all"):
        run_chat(client)
    if args.mode == "all":
        print("\n--- 加入动作格式提示词后 ---")
    if args.mode in ("prompt-tool", "all"):
        run_prompt_tool(client)


if __name__ == "__main__":
    main()
