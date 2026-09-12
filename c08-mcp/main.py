"""C08 MCP Client：启动 Server 子进程，发现、调用工具，并走通 LLM 完整闭环。

两条链路：
  1. 纯 MCP 层（不依赖 LLM）：stdio 初始化 → tools/list → tools/call → 错误路径，
     验证「发现工具、调用工具、工具报错」这条协议链路本身。
  2. LLM 完整闭环：把 tools/list 的结果转成 LLM 的 function-calling schema，
     交给 LLM 决定调哪个工具 → 客户端执行 tools/call → 结果回传 LLM → 最终回答。
     这一步证明 MCP 的边界到「工具发现与调用」为止，LLM 侧的决策是另一层。

用法:
    export DEEPSEEK_API_KEY=sk-xxx   # 跑 LLM 闭环用（可选；不设则只跑纯 MCP 层）
    python3 main.py

依赖: Python 3.10+，`pip install "mcp[cli]"`（MCP Python SDK v2）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path

from mcp import Client, StdioServerParameters

# LLM（只做「MCP 工具 → LLM 决策」的闭环，工具发现与调用本身不依赖它）
LLM_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/chat/completions")
# 两个名字都认：LLM_API_KEY 与上面两个变量同族（便于统一注入），
# DEEPSEEK_API_KEY 是 README 里给读者写的名字。
LLM_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")


def section(title: str) -> None:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def stdio_server() -> StdioServerParameters:
    """描述要启动的 MCP Server 子进程：当前 Python 解释器 + server.py。"""
    return StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).with_name("server.py"))],
    )


def call_llm(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """调用 LLM。带 tools 时走 function-calling，返回完整响应对象。"""
    payload: dict = {"model": MODEL, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    req = urllib.request.Request(
        LLM_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {LLM_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def tools_to_llm_schema(mcp_tools: list) -> list[dict]:
    """把 MCP 的 tools/list 结果，转成 LLM function-calling 的 tools 参数。

    MCP 工具定义里已经有 name / description / inputSchema，几乎原样对齐
    OpenAI 风格的 function-calling schema——这正是 MCP 被设计成「零翻译损耗」
    的地方。这里做的只是字段搬运。
    """
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.input_schema or {"type": "object", "properties": {}},
            },
        }
        for t in mcp_tools
    ]


async def demo_mcp_layer() -> None:
    """纯 MCP 层：发现、调用、错误路径。不依赖 LLM。"""
    section("[1] 纯 MCP 层：发现工具 → 调用工具 → 错误路径")
    server = stdio_server()
    async with Client(server) as client:
        listed = await client.list_tools()
        print(f"  发现工具: {[t.name for t in listed.tools]}")
        for t in listed.tools:
            print(f"    - {t.name}: {t.description}")

        result = await client.call_tool("add", {"a": 2, "b": 3})
        print(f"  调用 add(2, 3): {result.structured_content}")

        # 错误路径：调用一个不存在的工具。MCP 把错误也做成协议的一部分——
        # 不是抛异常，而是返回 is_error=True 的结果，错误信息放在 content 里。
        err = await client.call_tool("missing_tool", {})
        print(f"  错误场景（未知工具）: is_error={err.is_error}; {err.content[0].text}")


async def demo_llm_loop() -> None:
    """LLM 完整闭环：tools/list → 模型选工具 → tools/call → Observation → 回答。"""
    section("[2] LLM 完整闭环：MCP 工具 → LLM 决策 → 执行 → 回答")
    if not LLM_KEY:
        print("  （未设置 DEEPSEEK_API_KEY，跳过 LLM 闭环）")
        return

    question = "北京今天天气怎么样？顺便帮我算一下 12 加 30。"

    async with Client(stdio_server()) as client:
        # 1. tools/list：从 MCP Server 拿到工具清单。
        listed = await client.list_tools()
        llm_tools = tools_to_llm_schema(listed.tools)
        print(f"  问：{question}")
        print(f"  从 MCP 拿到 {len(listed.tools)} 个工具，转成 function-calling schema")

        # 2. 把工具交给 LLM，让模型决定调哪个（以及参数）。
        messages = [
            {"role": "system", "content": "你是助手，需要时调用工具回答用户问题。"},
            {"role": "user", "content": question},
        ]
        resp = call_llm(messages, tools=llm_tools)
        tool_calls = resp["choices"][0]["message"].get("tool_calls", [])
        if not tool_calls:
            print(f"  模型没有调用工具，直接回答: {resp['choices'][0]['message']['content']}")
            return

        # 3. 逐个执行模型要求的工具调用，把结果作为 Observation 回传。
        messages.append(resp["choices"][0]["message"])  # 含 tool_calls 的 assistant 消息
        for tc in tool_calls:
            fn = tc["function"]
            name, args = fn["name"], json.loads(fn["arguments"] or "{}")
            print(f"  模型选择调用 {name}({args})")
            result = await client.call_tool(name, args)
            observation = json.dumps(result.structured_content, ensure_ascii=False)
            print(f"  Observation: {observation}")
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": observation,
            })

        # 4. 把 Observation 回传 LLM，生成最终回答。
        final = call_llm(messages, tools=llm_tools)
        print(f"  最终回答: {final['choices'][0]['message']['content']}")


async def main() -> int:
    await demo_mcp_layer()
    await demo_llm_loop()
    print("\n" + "=" * 64)
    print("核心结论：MCP 标准化了「工具怎么被发现、怎么被调用」，")
    print("  但它不替 LLM 决策——选哪个工具、给什么参数，仍是 LLM 在 function-calling 层做的。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
