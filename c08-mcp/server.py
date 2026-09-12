"""C08 MCP Server：通过 STDIO 暴露工具，供 MCP Client 发现与调用。

这里暴露三个工具，覆盖两类用途：
  - get_weather / get_time：语义化工具，演示「LLM 真正需要『选择』用哪个」；
  - add：最小确定性工具，用于验收「发现 → 调用 → 返回」这条协议链路本身。

注意：STDIO 是协议通道，任何业务日志只能写 stderr，绝不能 print 到 stdout，
否则会污染 JSON-RPC 消息流，导致客户端解析失败。
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from mcp.server import MCPServer

mcp = MCPServer("c08-mcp-demo")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b


@mcp.tool()
def get_weather(city: str) -> str:
    """Get the current weather for a city. 演示用的确定性数据，不真的联网查天气。"""
    # 一个固定的假数据源，保证演示输出可复现、不依赖外部天气 API。
    fake = {
        "北京": "晴，24°C",
        "上海": "多云，27°C",
        "深圳": "阵雨，30°C",
    }
    return fake.get(city, f"{city} 暂无数据")


@mcp.tool()
def get_time() -> str:
    """Get the current server time."""
    return datetime.now(timezone.utc).isoformat()


def run_stdio() -> None:
    """以 STDIO 传输方式启动 Server。

    mcp.run() 默认走 stdio：从 stdin 读 JSON-RPC，把 JSON-RPC 写到 stdout。
    """
    mcp.run()


if __name__ == "__main__":
    # 兜底：把任何意外的业务打印重定向到 stderr，避免污染 stdout 协议流。
    sys.stderr.write("[c08-server] 启动 STDIO MCP Server\n")
    run_stdio()
