#!/usr/bin/env python3
"""C02 延伸：把 main.py 的"一轮"改造成 while 循环——Agent 雏形。

连续多轮工具调用：模型说要调工具 → 执行 → 回喂 → 再问，直到模型直接回答。
依赖: Python 3.10+，仅标准库（复用 main.py 里的工具与调用函数）。
"""

import main as base  # 复用 TOOLS / run_tool / call


def main() -> int:
    question = "北京现在天气怎么样？顺便看看上海"
    print(f"模型: {base.MODEL}\n问题: {question}\n" + "-" * 46)

    messages = [{"role": "user", "content": question}]
    rounds = 0
    while True:
        rounds += 1
        print(f"\n[第 {rounds} 轮] 问模型…")
        r = base.call(messages, tools=base.TOOLS)
        msg = r["choices"][0]["message"]

        if not msg.get("tool_calls"):
            print(f"[模型最后说] {msg['content']}")
            break

        messages.append({"role": "assistant", "content": None,
                         "tool_calls": msg["tool_calls"]})
        for tc in msg["tool_calls"]:
            fn = tc["function"]
            result = base.run_tool(fn["name"], fn["arguments"])
            print(f"[模型说] 调用 {fn['name']}({fn['arguments']}) → {result}")
            messages.append({"role": "tool",
                             "tool_call_id": tc["id"], "content": result})

        if rounds >= 5:  # 防死循环（生产里这是硬性控制）
            print("[保护] 超过最大轮数，停止")
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())