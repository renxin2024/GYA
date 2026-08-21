"""C08 MCP Server：通过 STDIO 暴露一个最小工具。"""

from mcp.server import MCPServer


mcp = MCPServer("c08-demo")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b


if __name__ == "__main__":
    # STDIO 是协议通道，不能向 stdout 打印业务日志。
    mcp.run()
