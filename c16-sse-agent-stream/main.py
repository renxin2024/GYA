#!/usr/bin/env python3
"""A dependency-free SSE stream that exposes one simulated Agent Run."""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


EVENTS = (
    ("1", "text.delta", {"runId": "run_demo", "delta": "我先运行测试。"}),
    ("2", "tool.started", {"runId": "run_demo", "tool": "run_tests", "callId": "call_1"}),
    ("3", "tool.completed", {"runId": "run_demo", "callId": "call_1", "summary": "3 个测试失败"}),
    ("4", "run.completed", {"runId": "run_demo"}),
)


def encode_event(event_id: str, event_type: str, payload: dict[str, str]) -> bytes:
    """Encode one complete SSE event. The final blank line is its boundary."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event_type}\ndata: {body}\n\n".encode("utf-8")


class AgentStreamHandler(BaseHTTPRequestHandler):
    server_version = "GYA-SSE-Demo/1.0"

    def do_GET(self) -> None:  # noqa: N802 - inherited HTTP handler name
        if self.path != "/events":
            self.send_error(404, "Use GET /events")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        for event_id, event_type, payload in EVENTS:
            self.wfile.write(encode_event(event_id, event_type, payload))
            self.wfile.flush()
            time.sleep(0.1)

        if self.server.once:  # type: ignore[attr-defined]
            self.server.shutdown()  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        print("[http]", format % args)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--once", action="store_true", help="Stop after one GET /events request.")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), AgentStreamHandler)
    server.once = args.once  # type: ignore[attr-defined]
    print(f"SSE endpoint: http://127.0.0.1:{args.port}/events")
    print("Open it with: curl -N http://127.0.0.1:%d/events" % args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
