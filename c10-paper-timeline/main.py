"""C10：用一个可重复的 ReAct 轨迹，观察论文思想如何落到循环。"""

def solve(question: str) -> list[tuple[str, str]]:
    trace = [("thought", "需要先查资料，再计算结果"), ("action", "lookup:agent"),
             ("observation", "agent = 会感知、规划并执行的系统"),
             ("action", "calculator:2+3"), ("observation", "5"),
             ("final", f"{question}：Agent 需要循环连接推理与行动")]
    return trace

if __name__ == "__main__":
    for kind, value in solve("什么是 Agent"):
        print(f"[{kind}] {value}")
