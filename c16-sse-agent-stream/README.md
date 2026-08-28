# C16 演示：SSE 让 Agent Run 变成事件流

这个零依赖服务模拟一次 Agent Run：文本增量、工具开始、工具完成、Run 终态依次写入同一条 SSE 响应。

它不调用 LLM，也不需要 API Key。目标是验证 SSE 的线协议与事件边界，而不是模拟模型能力。

## 前置环境

- Python 3.9+
- `curl`

## 运行

终端一启动服务：

```bash
python3 main.py --once
```

终端二订阅事件流：

```bash
curl -N http://127.0.0.1:8765/events
```

`--once` 会在一个客户端完整读完事件后退出，便于验证；去掉它则保持服务运行。

## 预期输出

```text
id: 1
event: text.delta
data: {"runId":"run_demo","delta":"我先运行测试。"}

id: 2
event: tool.started
data: {"runId":"run_demo","tool":"run_tests","callId":"call_1"}

id: 3
event: tool.completed
data: {"runId":"run_demo","callId":"call_1","summary":"3 个测试失败"}

id: 4
event: run.completed
data: {"runId":"run_demo"}
```

## 常见问题

1. `curl` 迟迟没有输出：确认使用了 `-N`，它会禁用客户端缓冲。
2. 地址已被占用：用 `python3 main.py --port 8766 --once`，并把 `curl` 的端口改为 `8766`。
3. 访问 `/` 返回 404：示例只暴露 `GET /events`，这是刻意保留的单一订阅入口。
