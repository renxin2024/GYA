#!/usr/bin/env python3
"""一个零依赖的 SSE 服务，用来暴露一次模拟的 Agent Run。

本示例刻意让 Agent 侧保持确定性：不调用真实 LLM 或真实工具。这样读者能把
注意力放在传输契约上：同一个 HTTP 响应保持打开，服务端持续写入多个完整 SSE 帧。
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# 生产系统中的这些事件通常来自 Run 状态存储或事件总线。这里用固定序列，便于
# 读者看清顺序，也让每次运行的结果可重复。
#
# `event` 是 SSE 协议字段；`tool.started` 这类名称则是 Agent 产品自行设计的
# 应用层事件契约，并不是 SSE 标准规定的事件名。
EVENTS = (
    ("1", "text.delta", {"runId": "run_demo", "delta": "我先运行测试。"}),
    ("2", "tool.started", {"runId": "run_demo", "tool": "run_tests", "callId": "call_1"}),
    ("3", "tool.completed", {"runId": "run_demo", "callId": "call_1", "summary": "3 个测试失败"}),
    ("4", "run.completed", {"runId": "run_demo"}),
)


def encode_event(event_id: str, event_type: str, payload: dict[str, str]) -> bytes:
    """编码一个完整的 SSE 帧。

    SSE 是按行解析的文本协议，而不是任意 JSON 字节块的连续拼接。`id` 让浏览器
    重连时能携带 Last-Event-ID；`event` 决定事件监听器；`data` 承载本示例的 JSON
    payload。末尾的 `\n\n` 必不可少：它标记一条事件结束，EventSource 才会立即分发。
    """
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event_type}\ndata: {body}\n\n".encode("utf-8")


class AgentStreamHandler(BaseHTTPRequestHandler):
    """仅暴露一次模拟 Agent Run 的只读事件流。

    创建或取消 Run 通常应由独立的 POST endpoint 处理。这个小服务只保留
    `GET /events`，让 SSE 的“服务端单向下行”特性更直观。
    """

    server_version = "GYA-SSE-Demo/1.0"

    def do_GET(self) -> None:  # noqa: N802 - inherited HTTP handler name
        # 不要把任意 URL 悄悄变成事件流。真实服务应使用明确的订阅 endpoint，并在
        # 暴露某个 Run 的事件前，完成调用方鉴权和该 Run 的访问授权。
        if self.path != "/events":
            self.send_error(404, "Use GET /events")
            return

        # EventSource 接受状态码为 200、内容类型为 SSE 的响应。`Cache-Control`
        # 防止中间层把旧事件流当作当前 Agent Run 的实时结果返回。
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        for event_id, event_type, payload in EVENTS:
            # write 只会把字节交给服务端缓冲区。每帧后都 flush，客户端才能在 Run
            # 完成前看到进度。反向代理仍可能缓冲，这属于 Python 进程之外的生产问题。
            self.wfile.write(encode_event(event_id, event_type, payload))
            self.wfile.flush()
            time.sleep(1)

        if self.server.once:  # type: ignore[attr-defined]
            # `--once` 是测试模式，不是 SSE 的常规行为。它让 curl/CI 在一个订阅者
            # 消费完固定事件后确定性结束。去掉该参数后，*服务进程* 会继续等待后续
            # 客户端；但本示例中每个响应仍会在写完四个固定事件后结束。
            self.server.shutdown()  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        print("[http]", format % args)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--once", action="store_true", help="Stop after one GET /events request.")
    args = parser.parse_args()

    # 只绑定回环地址：这是学习用服务，不应直接暴露到公网。
    # ThreadingHTTPServer 会为每个订阅客户端分配处理线程，避免一个慢客户端阻塞
    # 其他客户端接收各自的事件流。
    server = ThreadingHTTPServer(("127.0.0.1", args.port), AgentStreamHandler)
    # BaseHTTPRequestHandler 不知道 CLI 参数；把这个狭义的测试模式设置挂到服务实例上，
    # 让 handler 决定是否在完成一次订阅后关停服务。
    server.once = args.once  # type: ignore[attr-defined]
    print(f"SSE endpoint: http://127.0.0.1:{args.port}/events")
    print("Open it with: curl -N http://127.0.0.1:%d/events" % args.port)
    # 此循环故意保持长期运行。常规使用时按 Ctrl-C 停止；`--once` 则要求上面的
    # handler 在处理完一次请求后关闭服务。
    server.serve_forever()


if __name__ == "__main__":
    main()
