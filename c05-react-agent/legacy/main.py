#!/usr/bin/env python3
"""C05 main.py：CLI 入口——运行一个 ReAct Agent 并打印完整 trace。

用法:
    export DEEPSEEK_API_KEY=sk-xxx
    python3 main.py "北京天气怎么样？顺便算一下 123*456"

    # 交互模式（连续提问）：
    python3 main.py -i
"""

import sys

from react_loop import ReactAgent
from tools import build_registry


def run_single(question: str) -> None:
    agent = ReactAgent(build_registry())
    state = agent.run(question)
    print("\n" + "=" * 60)
    print("最终答案:")
    print(state.final_answer)
    print("\n--- 执行轨迹 ---")
    print(state.summary())


def run_interactive() -> None:
    agent = ReactAgent(build_registry())
    print("ReAct Agent 交互模式（输入 exit 退出）")
    while True:
        q = input(">>> ")
        if q.strip().lower() in ("exit", "quit"):
            break
        state = agent.run(q)
        print(f"\n答案: {state.final_answer}")


def main() -> int:
    if not API_KEY_ENV_OK():
        print("请先设置 DEEPSEEK_API_KEY 环境变量（https://platform.deepseek.com 获取）")
        return 1
    args = sys.argv[1:]
    if args and args[0] == "-i":
        run_interactive()
    elif args:
        run_single(" ".join(args))
    else:
        # 默认演示任务：需要连续多步工具调用
        run_single("北京天气怎么样？顺便算一下 123*456，最后把两个答案整理成一句话。")
    return 0


def API_KEY_ENV_OK() -> bool:
    import os
    return bool(os.environ.get("DEEPSEEK_API_KEY", ""))


if __name__ == "__main__":
    raise SystemExit(main())
