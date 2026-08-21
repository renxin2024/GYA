"""C08 MCP Client：启动 Server 子进程，发现并调用工具。"""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).with_name("server.py"))],
    )

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as client:
            await client.initialize()
            print(f"[1] 初始化 MCP Server: {client.server_capabilities}")

            listed = await client.list_tools()
            print(f"[2] 发现工具: {[tool.name for tool in listed.tools]}")

            result = await client.call_tool("add", {"a": 2, "b": 3})
            print(f"[3] 调用 add(2, 3): {result.content[0].text}")

            unknown = await client.call_tool("missing_tool", {})
            print(f"[4] 错误场景: is_error={unknown.is_error}; {unknown.content[0].text}")


if __name__ == "__main__":
    asyncio.run(main())
