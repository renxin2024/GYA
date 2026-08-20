#!/usr/bin/env python3
"""C04 演示：工具注册表与 ToolResponse 协议

C02 的 demo 里只有 1 个工具，调用方用 `if name == "get_weather"` 硬编码分发。
本篇演示工具多了以后的正规做法：

  1. ToolRegistry（注册表）：工具动态注册/发现/调用/下线
  2. ToolResponse（结构化响应）：status/text/data/error_info 四件套
  3. 错误处理：调用不存在的工具 → 显式错误码，而不是崩掉
  4. 下线：unregister 后模型 schema 里没有它，模型就不会再调用

关键对比（硬编码 vs 注册表）：
  - 硬编码：加工具要改 main.py 的 if-else → 重启
  - 注册表：加工具 = 注册一个函数 → 调用方代码零改动

用法:
    export DEEPSEEK_API_KEY=sk-xxx
    python3 registry_demo.py

依赖: Python 3.10+，仅标准库（urllib），无需安装任何包。
"""

import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

API_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/chat/completions")
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")


# ---------------------------------------------------------------
# 1. ToolResponse：工具返回的结构化协议
#    text 给 LLM 看（自然语言），status/data/error_info 给程序用
# ---------------------------------------------------------------
@dataclass
class ToolResponse:
    status: str                  # SUCCESS / PARTIAL / ERROR
    text: str                    # 给 LLM 读的格式化文本
    data: Dict[str, Any] = field(default_factory=dict)       # 给程序用的结构化数据
    error_info: Optional[Dict] = None                        # 仅 ERROR 时有


# ---------------------------------------------------------------
# 2. ToolRegistry：工具注册表
#    register / unregister / execute / list_schemas
# ---------------------------------------------------------------
class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Dict] = {}

    def register(self, fn: Callable, name: str, description: str,
                 parameters: Dict) -> None:
        """注册一个工具：函数 + 元数据（给 LLM 看的 schema）。"""
        self._tools[name] = {
            "fn": fn,
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            },
        }

    def unregister(self, name: str) -> None:
        """下线一个工具：从注册表移除（下次注入 LLM 的 schema 就没有它）。"""
        self._tools.pop(name, None)

    def list_schemas(self) -> List[Dict]:
        """给 API 层用的工具列表（直接塞进 tools 参数）。"""
        return [t["schema"] for t in self._tools.values()]

    def execute(self, name: str, arguments: Dict) -> ToolResponse:
        """调用方入口：按名字路由到真实函数，返回结构化响应。"""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResponse(
                status="ERROR",
                text=f"错误：工具 {name} 不存在。可用工具: {', '.join(self._tools)}",
                error_info={"code": "UNKNOWN_TOOL", "tool": name},
            )
        try:
            result = tool["fn"](**arguments)
            return ToolResponse(status="SUCCESS", text=str(result), data={"result": result})
        except TypeError as e:
            return ToolResponse(
                status="ERROR",
                text=f"错误：参数不正确。{e}",
                error_info={"code": "INVALID_PARAM", "message": str(e)},
            )
        except Exception as e:
            return ToolResponse(
                status="ERROR",
                text=f"错误：执行失败。{e}",
                error_info={"code": "EXECUTION_ERROR", "message": str(e)},
            )


# ---------------------------------------------------------------
# 3. 工具实现（真实函数，与注册表解耦）
# ---------------------------------------------------------------
FAKE_WEATHER = {
    "北京": "多云，25℃，东北风 3 级",
    "上海": "阵雨，28℃，东南风 2 级",
    "深圳": "晴，31℃，南风 2 级",
}


def get_weather(city: str) -> str:
    """查询城市天气（简化：查本地表）。"""
    if city not in FAKE_WEATHER:
        raise ValueError(f"暂无 {city} 的天气数据")
    return f"{city}: {FAKE_WEATHER[city]}"


def calculator(expression: str) -> str:
    """安全计算器：只允许数字和 + - * / ( )（防止任意代码执行）。"""
    allowed = set("0123456789+-*/(). ")
    if not all(c in allowed for c in expression):
        raise ValueError("表达式包含非法字符")
    return str(eval(expression))  # noqa: S307 — 演示用，生产请用 ast 或 arithmetics


def search_notes(query: str) -> str:
    """搜索笔记（简化：返回固定结果）。"""
    return f"找到与『{query}』相关的笔记 3 条（演示数据）"


# ---------------------------------------------------------------
# 4. 组装注册表
# ---------------------------------------------------------------
def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        get_weather, "get_weather",
        "查询指定城市的当前天气。城市例：北京、上海、深圳",
        {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名"}
            },
            "required": ["city"],
        },
    )
    reg.register(
        calculator, "calculator",
        "执行算术表达式计算。例如：123*456、 (1+2)*3",
        {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "算术表达式"}
            },
            "required": ["expression"],
        },
    )
    reg.register(
        search_notes, "search_notes",
        "在个人知识库中搜索笔记。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"}
            },
            "required": ["query"],
        },
    )
    return reg


# ---------------------------------------------------------------
# 5. 与模型交互：一次"模型说 → 注册表执行 → 回喂"闭环
# ---------------------------------------------------------------
def call(messages, tools=None):
    payload = {"model": MODEL, "messages": messages, "tools": tools, "stream": False}
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["choices"][0]["message"]


def run_agent_round(reg: ToolRegistry, question: str) -> None:
    """跑一轮完整闭环：问题 → 模型说调工具 → 注册表执行 → 回喂 → 模型总结。"""
    messages: List[Dict[str, Any]] = [{"role": "user", "content": question}]
    msg = call(messages, tools=reg.list_schemas())
    print(f"问题: {question}")

    if not msg.get("tool_calls"):
        print(f"[模型直接回答] {msg['content']}")
        return

    # assistant 消息原样回传（含 reasoning_content + tool_calls，DeepSeek thinking 模式要求）
    messages.append(msg)
    for tc in msg["tool_calls"]:
        fn = tc["function"]
        args = json.loads(fn["arguments"] or "{}")
        print(f"  [模型说] 调用 {fn['name']}({json.dumps(args, ensure_ascii=False)})")
        resp = reg.execute(fn["name"], args)
        print(f"  [注册表] status={resp.status}, text={resp.text}")
        if resp.error_info:
            print(f"  [注册表] error_code={resp.error_info.get('code')}")
        messages.append({"role": "tool", "tool_call_id": tc["id"], "content": resp.text})

    r2 = call(messages)
    print(f"[模型总结] {r2.get('content')}\n")


def main() -> int:
    if not API_KEY:
        print("请先设置 DEEPSEEK_API_KEY 环境变量（https://platform.deepseek.com 获取）")
        return 1

    reg = build_registry()
    print(f"模型: {MODEL}")
    print(f"已注册工具: {list(reg._tools.keys())}")
    print("=" * 60)

    # ---------- 1. 正常闭环：模型发现并调用工具 ----------
    print("\n[1] 正常闭环：模型从 schema 发现工具并调用")
    run_agent_round(reg, "北京现在天气怎么样？顺便算一下 123*456")

    # ---------- 2. 错误处理：调用不存在的工具（模型幻觉） ----------
    print("[2] 错误处理：直接调用不存在的工具（模拟模型幻觉）")
    resp = reg.execute("send_email", {"to": "a@b.com"})
    print(f"status={resp.status}, error_code={resp.error_info.get('code')}")
    print(f"text={resp.text}\n")

    # ---------- 3. 参数错误 ----------
    print("[3] 错误处理：参数不对（calculator 缺 expression）")
    resp = reg.execute("calculator", {})
    print(f"status={resp.status}, error_code={resp.error_info.get('code')}")
    print(f"text={resp.text}\n")

    # ---------- 4. 下线：unregister 后模型不再调用它 ----------
    print("[4] 下线工具：unregister('get_weather')")
    reg.unregister("get_weather")
    print(f"剩余工具: {list(reg._tools.keys())}")
    print("现在问天气，模型会怎么做？")
    run_agent_round(reg, "北京现在天气怎么样？")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
