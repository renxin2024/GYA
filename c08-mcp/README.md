# C08 演示：MCP 工具发现与调用 + LLM 完整闭环

本示例演示 MCP 的最小闭环，分两层：

1. **纯 MCP 层**：客户端通过 STDIO 启动独立的 MCP Server，完成工具发现、工具调用、错误返回。
2. **LLM 完整闭环**：把 `tools/list` 的结果转成 LLM function-calling schema，交给 LLM 决定调哪个工具 → 客户端执行 `tools/call` → 结果回传 LLM → 最终回答。

## 前置环境

| 项 | 要求 |
|----|------|
| Python | 3.10+ |
| 依赖 | `pip install "mcp[cli]"`（MCP Python SDK v2） |
| LLM（可选） | DeepSeek 官方 Key，只跑第 [2] 段闭环；不设则只跑纯 MCP 层 |

## 运行

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install "mcp[cli]"
export DEEPSEEK_API_KEY=sk-你的key   # 可选，跑 [2] 闭环用
python3 main.py
```

## 预期输出

```text
[1] 纯 MCP 层：发现工具 → 调用工具 → 错误路径
  发现工具: ['add', 'get_weather', 'get_time']
    - add: Add two integers and return the result.
    - get_weather: Get the current weather for a city.
    - get_time: Get the current server time.
  调用 add(2, 3): {'result': 5}
  错误场景（未知工具）: is_error=True; Unknown tool: missing_tool

[2] LLM 完整闭环：MCP 工具 → LLM 决策 → 执行 → 回答
  问：北京今天天气怎么样？顺便帮我算一下 12 加 30。
  从 MCP 拿到 3 个工具，转成 function-calling schema
  模型选择调用 get_weather({'city': '北京'})
  Observation: {"result": "晴，24°C"}
  模型选择调用 add({'a': 12, 'b': 30})
  Observation: {"result": 42}
  最终回答: ...北京今天天气晴，24°C；12 + 30 = 42...
```

## 失败排查

1. **`AttributeError: 'Tool' object has no attribute 'inputSchema'`**：v2 SDK 字段名改成了 snake_case（`input_schema` / `structured_content`），不是 v1 的 `inputSchema` / `content[0].text`。看的是 v1 旧教程的坑。
2. **`ModuleNotFoundError: No module named 'mcp.client.stdio'`**：v1 用 `from mcp.client.stdio import stdio_client` + `ClientSession`，v2 改成 `from mcp import Client, StdioServerParameters`。旧代码直接跑 v2 会挂。
3. **`RuntimeError: Client must be used within an async context manager`**：v2 的 `Client` 只在 `async with` 里才真正连接，不能先构造再在别处用。

## 关键点

- **STDIO 是协议通道**：Server 的任何业务打印必须走 stderr，`print()` 到 stdout 会污染 JSON-RPC 消息流。
- **错误也是协议的一部分**：未知工具不抛异常，而是返回 `is_error=True` 的结果对象。
- **MCP 的边界到「工具发现与调用」为止**：选哪个工具、给什么参数，仍是 LLM 在 function-calling 层做的。
