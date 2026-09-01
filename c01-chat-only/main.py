#!/usr/bin/env python3
"""C01 演示：一次最小调用，看清模型、API、Runtime 的职责边界。

这个 demo 只做一件事：把「一次调用里谁发了什么、谁收到了什么」变成可观察的 Trace。
它不会自动查天气、也不会调用工具——这正是 C01 要让你看清的边界。

用法:
    # 不联网，只打印 Runtime 会组装出什么样的请求
    python3 main.py --dry-run "上海今天天气怎么样？"

    # 可选注入一条 system 级运行时提示
    RUNTIME_CONTEXT="只回答可以从请求证明的事实" python3 main.py --dry-run "上海今天天气怎么样？"

    # 真实调用 DeepSeek
    export DEEPSEEK_API_KEY=sk-xxx
    python3 main.py "上海今天天气怎么样？"

依赖: Python 3.9+，仅标准库。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

REDACTED_RESPONSE_KEYS = {"id", "request_id", "system_fingerprint"}


def emit(event: str, owner: str, **fields: Any) -> None:
    print(json.dumps({"event": event, "owner": owner, **fields}, ensure_ascii=False, separators=(",", ":")))


def redact_response(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "<redacted>" if k in REDACTED_RESPONSE_KEYS else redact_response(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_response(item) for item in value]
    return value


def sanitized_response_text(raw: str) -> str:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return json.dumps(redact_response(parsed), ensure_ascii=False, separators=(",", ":"))


def build_payload(model: str, prompt: str, runtime_context: str = "") -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    if runtime_context:
        messages.append({"role": "system", "content": runtime_context})
    messages.append({"role": "user", "content": prompt})
    return {"model": model, "messages": messages, "stream": False}


def redact_sensitive_fields(text: str) -> str:
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "<redacted>", text)
    text = re.sub(r"(?<!\d)\d{17}[\dXx](?!\d)", "<redacted>", text)
    return text


def trace_payload(payload: dict[str, Any]) -> dict[str, Any]:
    traced = json.loads(json.dumps(payload, ensure_ascii=False))
    for message in traced["messages"]:
        if message["role"] == "system":
            message["content"] = "<redacted>"
        elif message["role"] == "user":
            message["content"] = redact_sensitive_fields(message["content"])
    return traced


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", default="上海今天的天气和气温是多少？")
    parser.add_argument("--dry-run", action="store_true", help="不联网，只打印请求 Trace")
    args = parser.parse_args()

    api_url = os.environ.get("LLM_API_URL", "https://api.deepseek.com/chat/completions")
    model = os.environ.get("LLM_MODEL", "deepseek-v4-flash")
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY", "")
    if not args.dry_run and not api_key:
        print("请先设置 DEEPSEEK_API_KEY 或 LLM_API_KEY。", file=sys.stderr)
        return 2

    runtime_context = os.environ.get("RUNTIME_CONTEXT", "").strip()
    if runtime_context:
        context_bytes = runtime_context.encode("utf-8")
        emit("context.prepared", "client_runtime", source="env:RUNTIME_CONTEXT", role="system",
             content_bytes=len(context_bytes), sha256=hashlib.sha256(context_bytes).hexdigest(),
             content_redacted=True)
    else:
        emit("context.skipped", "client_runtime", source="env:RUNTIME_CONTEXT", reason="empty_optional_context")

    payload = build_payload(model, args.prompt, runtime_context)
    emit("request.prepared", "client_runtime", method="POST", url=api_url,
         headers={"Content-Type": "application/json", "Authorization": "Bearer <redacted>"},
         body=trace_payload(payload))
    if args.dry_run:
        emit("run.finished", "client_runtime", outcome="dry_run_no_network")
        return 0

    request = urllib.request.Request(api_url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
                                     method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = response.status
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8", errors="replace")
    emit("response.received", "model_api", status=status, body_raw=sanitized_response_text(raw))
    emit("run.finished", "client_runtime", outcome="success" if 200 <= status < 300 else "http_error")
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
