"""C11：trace -> trajectory -> mining -> recall 的离线最小闭环。"""

traces = [
    {"task": "发布", "steps": ["检查", "构建", "验证"], "success": True},
    {"task": "发布", "steps": ["检查", "构建"], "success": False},
]

def mine(items: list[dict]) -> dict[str, list[str]]:
    good = [step for item in items if item["success"] for step in item["steps"]]
    return {"发布": list(dict.fromkeys(good))}

if __name__ == "__main__":
    memory = mine(traces)
    print(f"[1] traces={len(traces)}")
    print(f"[2] mined trajectory: {memory['发布']}")
    print(f"[3] recall for 发布: {' -> '.join(memory['发布'])}")
