"""C08 离线回归测试：不依赖 LLM，验证 MCP 纯协议层。

覆盖：
  - 工具发现：tools/list 能拿到 server 暴露的工具名；
  - 成功调用：add(2,3) == 5；
  - 失败路径：调用未知工具返回 is_error=True；
  - schema 转换：tools/list 的结果能转成 LLM function-calling schema。

不涉及真实 LLM 调用（那部分由 main.py 的 [2] 段在有 Key 时验证）。
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

from mcp import Client, StdioServerParameters

from main import stdio_server, tools_to_llm_schema


class TestMcpProtocol(unittest.TestCase):
    """纯协议层的确定性断言，可离线运行。"""

    def test_discover_and_call(self) -> None:
        async def run() -> None:
            async with Client(stdio_server()) as client:
                listed = await client.list_tools()
                names = [t.name for t in listed.tools]
                self.assertIn("add", names)
                self.assertIn("get_weather", names)

                result = await client.call_tool("add", {"a": 2, "b": 3})
                self.assertEqual(result.structured_content, {"result": 5})

        asyncio.run(run())

    def test_unknown_tool_returns_error(self) -> None:
        async def run() -> None:
            async with Client(stdio_server()) as client:
                err = await client.call_tool("missing_tool", {})
                self.assertTrue(err.is_error)
                self.assertIn("Unknown tool", err.content[0].text)

        asyncio.run(run())

    def test_schema_conversion(self) -> None:
        async def run() -> None:
            async with Client(stdio_server()) as client:
                listed = await client.list_tools()
                schema = tools_to_llm_schema(listed.tools)
                self.assertEqual(len(schema), len(listed.tools))
                self.assertEqual(schema[0]["type"], "function")
                self.assertIn("name", schema[0]["function"])
                self.assertIn("parameters", schema[0]["function"])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
