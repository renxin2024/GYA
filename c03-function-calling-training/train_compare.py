#!/usr/bin/env python3
"""C03 演示：模型"会调用工具"的能力是从哪来的？

同一个问题，三种问法，对比输出：

  A) 裸问（不带 tools 参数）
     → 模型只会文本补全：回答"我无法实时获取天气"，没有 tool_calls 字段

  B) 带 tools 参数（API 层注入工具定义 + 后训练教出的格式约定）
     → 模型输出结构化 tool_calls 数组，每个调用带独立 id，
       调用方遍历即可逐个执行（无需正则解析）

  C) 纯 prompt 手写格式（不带 tools 参数，靠 system prompt 要求"输出 JSON"）
     → 模型"努力"遵守格式，但没有 API 层保证：
       同一问题跑多次，有时输出两个 JSON、有时漏掉一个
     → 调用方靠正则/JSON 解析"捞"工具调用，数量都不保证

结论：稳定输出工具调用格式，是后训练阶段教出来的 + API 层注入保证的，
不是你在 prompt 里写几句"请输出 JSON"就能稳住的。

用法:
    export DEEPSEEK_API_KEY=sk-xxx
    python3 train_compare.py

依赖: Python 3.10+，仅标准库（urllib），无需安装任何包。
"""

import json
import os
import re
import urllib.request

API_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/chat/completions")
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

# ---------------------------------------------------------------
# 同一个工具定义：方式 B 作为 API 参数传入；方式 C 作为文本写进 prompt
# ---------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询指定城市的当前天气。城市例：北京、上海、深圳",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名"}
                },
                "required": ["city"],
            },
        },
    }
]

# 方式 C 用的 system prompt：把工具定义"翻译"成文本，要求模型输出 JSON
PROMPT_WITH_TOOLS = """你有以下工具可用：
- get_weather(city): 查询指定城市的当前天气。城市例：北京、上海、深圳

需要使用时，按以下 JSON 格式输出（不要输出其他任何内容）：
{"name": "<工具名>", "arguments": {"city": "<城市名>"}}

不需要使用时，直接回答用户问题。"""

# 双城市问题：需要两个工具调用，才能看出格式能力差异
QUESTION = "北京和上海现在天气分别怎么样？"
CITIES = ["北京", "上海"]


def call(messages, tools=None):
    """向模型发一次请求，返回 message 对象。"""
    payload = {"model": MODEL, "messages": messages, "tools": tools, "stream": False}
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
    return data["choices"][0]["message"]


def extract_tool_calls_manually(text: str):
    """方式 C 的调用方解析：模拟 V3 手写 Agent 的正则/JSON 解析。

    纯 prompt 模式下模型可能输出：
      - 一整段合法 JSON            → json.loads 直接成功
      - 一行一个 JSON（多个调用）  → 逐行解析
      - 裹在散文里的 JSON          → 正则"捞"
      - 只输出了一个（漏了第二个） → 解析成功但数量不对
    返回 [(工具名, 参数字符串), ...]，解析不出来返回空列表。
    """
    results = []
    candidates = []
    # 1. 整段 JSON
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "name" in obj:
            candidates.append(obj)
        elif isinstance(obj, list):
            candidates.extend([o for o in obj if isinstance(o, dict) and "name" in o])
    except json.JSONDecodeError:
        pass
    # 2. 逐行 JSON（模型可能输出 一行一个调用）
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and "name" in obj:
                candidates.append(obj)
        except json.JSONDecodeError:
            pass
    # 3. 正则"捞"（模型把 JSON 裹进散文）
    for m in re.finditer(r"\{.*?\}", text, re.DOTALL):
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and "name" in obj:
                candidates.append(obj)
        except json.JSONDecodeError:
            pass
    seen = set()
    for obj in candidates:
        key = obj["name"] + str(obj.get("arguments"))
        if key in seen:
            continue
        seen.add(key)
        results.append((obj["name"], json.dumps(obj.get("arguments", {}), ensure_ascii=False)))
    return results


def main() -> int:
    if not API_KEY:
        print("请先设置 DEEPSEEK_API_KEY 环境变量（https://platform.deepseek.com 获取）")
        return 1

    print(f"模型: {MODEL}")
    print(f"问题: {QUESTION}")
    print("=" * 60)

    # ---------- A) 裸问：无 tools ----------
    print("\n[A] 不带 tools 参数（模型只会文本补全）")
    print("-" * 60)
    msg_a = call([{"role": "user", "content": QUESTION}])
    print("content:", repr(msg_a.get("content")))
    print("tool_calls:", msg_a.get("tool_calls"))
    if not msg_a.get("tool_calls"):
        print(">>> 没有 tool_calls 字段 → 模型不知道『可以用』工具，只会说话")

    # ---------- B) 带 tools 参数 ----------
    print("\n[B] 带 tools 参数（API 层注入 + 后训练格式约定）")
    print("-" * 60)
    msg_b = call([{"role": "user", "content": QUESTION}], tools=TOOLS)
    print("content:", repr(msg_b.get("content")))
    tcs = msg_b.get("tool_calls") or []
    print("tool_calls:", json.dumps(tcs, ensure_ascii=False, indent=2))
    if tcs:
        print(f">>> 模型输出 {len(tcs)} 个结构化对象，每个带独立 id，调用方可直接执行")

    # ---------- C) 纯 prompt 手写格式（无 tools 参数） ----------
    print("\n[C] 不带 tools 参数，只靠 system prompt 要求输出 JSON（跑 5 次）")
    print("-" * 60)
    c_ok = 0
    for i in range(5):
        msg_c = call([
            {"role": "system", "content": PROMPT_WITH_TOOLS},
            {"role": "user", "content": QUESTION},
        ])
        raw = msg_c.get("content") or ""
        parsed = extract_tool_calls_manually(raw)
        names = [p[0] for p in parsed]
        got = len(parsed)
        want = len(CITIES)
        status = "✓ 数量正好" if got == want else f"✗ 漏了 {want - got} 个" if got < want else f"✗ 多了 {got - want} 个"
        print(f"第{i+1}次: 解析到 {got} 个工具调用 {names}  {status}")
        print(f"        原始输出: {raw!r}"[:150])
        if got == want:
            c_ok += 1
    print(f">>> 方式 C 5 次里 {c_ok} 次能解析出恰好 2 个工具调用（其余会漏）")

    # ---------- D) 稳定性统计 ----------
    print("\n[D] 稳定性对比：方式 B vs 方式 C 各跑 5 次，统计输出完整性")
    print("-" * 60)
    n = 5
    ok_b = ok_c = 0
    for _ in range(n):
        mb = call([{"role": "user", "content": QUESTION}], tools=TOOLS)
        if len(mb.get("tool_calls") or []) == len(CITIES):
            ok_b += 1
        mc = call([
            {"role": "system", "content": PROMPT_WITH_TOOLS},
            {"role": "user", "content": QUESTION},
        ])
        if len(extract_tool_calls_manually(mc.get("content") or "")) == len(CITIES):
            ok_c += 1
    print(f"方式 B（带 tools 参数）: {ok_b}/{n} 次输出完整的 {len(CITIES)} 个 tool_calls")
    print(f"方式 C（纯 prompt 手写）: {ok_c}/{n} 次能被解析器完整捞到 {len(CITIES)} 个调用")
    print("\n提示：B 的稳定性来自 API 层 + 后训练；C 的成败取决于模型的『自觉』和你的解析器运气。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
