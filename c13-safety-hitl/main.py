"""C13：危险动作先生成审批请求，审批通过后才执行。"""

def request(action: str) -> dict[str, str]:
    return {"action": action, "status": "pending", "reason": "会修改外部状态"}

def approve(ticket: dict[str, str], decision: str) -> str:
    ticket["status"] = decision
    return "已执行：" + ticket["action"] if decision == "approved" else "已拒绝，未执行"

if __name__ == "__main__":
    ticket = request("删除临时文件")
    print(f"[1] 审批单: {ticket}")
    print("[2] 人工决定: approved")
    print("[3] " + approve(ticket, "approved"))
