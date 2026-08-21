# C08 演示：MCP 工具发现与调用

本示例演示 MCP 的最小闭环：客户端通过 STDIO 启动独立的 MCP Server，完成初始化、工具发现、工具调用和错误返回。

## 运行

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 main.py
```

## 预期输出

```text
[1] 初始化 MCP Server: experimental={} logging=None prompts=PromptsCapability(list_changed=False) resources=ResourcesCapability(subscribe=False, list_changed=False) tools=ToolsCapability(list_changed=False) completions=None extensions=None tasks=None
[2] 发现工具: ['add']
[3] 调用 add(2, 3): 5
[4] 错误场景: is_error=True; Unknown tool: missing_tool
```
