"""C15：把客服系统拆成可观察的事件链。"""

def handle(message: str) -> list[tuple[str, str]]:
    return [("channel", message), ("route", "售后 Agent"),
            ("retrieve", "订单知识与会话记忆"), ("decision", "需要人工确认退款"),
            ("handoff", "创建 HITL 工单")]

if __name__ == "__main__":
    for kind, value in handle("我要申请退款"):
        print(f"[{kind}] {value}")
