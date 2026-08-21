"""C14：按任务复杂度路由，并用 token 估算成本。"""

MODELS = {"cheap": {"price": 1, "limit": 100}, "strong": {"price": 4, "limit": 40}}

def route(task: str) -> str:
    return "strong" if len(task) > 12 else "cheap"

def charge(model: str, tokens: int) -> int:
    if tokens > MODELS[model]["limit"]:
        raise ValueError("rate limit exceeded")
    return tokens * MODELS[model]["price"]

if __name__ == "__main__":
    task = "解释一个复杂的多 Agent 调度故障"
    model = route(task)
    print(f"[1] route={model}")
    print(f"[2] estimated_units={charge(model, 8)}")
    try:
        charge(model, 999)
    except ValueError as exc:
        print(f"[3] fallback boundary: {exc}")
