#!/usr/bin/env python3
"""C01 演示：一个只会说话的模型（命令行聊天）

启动后你就能和模型对话——它说的每句话，底层都是一次
"给定前文 token，预测下一个 token" 的重复。

用法:
    export DEEPSEEK_API_KEY=sk-xxx
    python3 chat.py

依赖: Python 3.10+，仅标准库（urllib），无需安装任何包。
"""

import json
import os
import sys
import urllib.request

API_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/chat/completions")
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

HISTORY: list[dict] = []


def ask(user_text: str) -> str:
    """把整个对话历史发给模型，返回它补全出来的下一个回复。"""
    HISTORY.append({"role": "user", "content": user_text})
    payload = {
        "model": MODEL,
        "messages": HISTORY,
        "stream": False,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    reply = data["choices"][0]["message"]["content"]
    HISTORY.append({"role": "assistant", "content": reply})
    return reply


def main() -> int:
    if not API_KEY:
        print("请先设置 DEEPSEEK_API_KEY 环境变量（https://platform.deepseek.com 获取）")
        return 1

    print(f"模型: {MODEL}")
    print("你正在和一个只会说话的模型聊天。输入 exit 退出。\n")
    while True:
        try:
            user_text = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if user_text.lower() in ("exit", "quit", "退出"):
            return 0
        print(f"模型 > {ask(user_text)}\n")


if __name__ == "__main__":
    sys.exit(main())
