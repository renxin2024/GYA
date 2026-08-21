"""C12：主管把任务拆给两个工人，再汇总结果。"""

def worker(role: str, task: str) -> str:
    return f"{role}完成：{task}"

def supervisor(task: str) -> str:
    pieces = [worker("资料员", f"收集 {task} 的事实"), worker("审稿员", f"检查 {task} 的风险")]
    return "主管汇总：" + "；".join(pieces)

if __name__ == "__main__":
    print("[1] 编排模式: supervisor-worker")
    print("[2] " + supervisor("MCP"))
