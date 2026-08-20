#!/usr/bin/env python3
"""C05 tools.py：工具系统（ToolRegistry + ToolResponse + 三个工具）。

复用 C04 的注册表设计——工具注册/调用/下线统一管理，
ReAct 主循环只依赖 execute() 一个入口。
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolResponse:
    status: str                  # SUCCESS / PARTIAL / ERROR
    text: str                    # 给 LLM 读的格式化文本
    data: Dict[str, Any] = field(default_factory=dict)
    error_info: Optional[Dict] = None


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Dict] = {}

    def register(self, fn: Callable, name: str, description: str,
                 parameters: Dict) -> None:
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
        self._tools.pop(name, None)

    def list_schemas(self) -> List[Dict]:
        return [t["schema"] for t in self._tools.values()]

    def execute(self, name: str, arguments: Dict) -> ToolResponse:
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
# 工具实现
# ---------------------------------------------------------------
FAKE_WEATHER = {
    "北京": "多云，25℃，东北风 3 级",
    "上海": "阵雨，28℃，东南风 2 级",
    "深圳": "晴，31℃，南风 2 级",
}


def get_weather(city: str) -> str:
    if city not in FAKE_WEATHER:
        raise ValueError(f"暂无 {city} 的天气数据")
    return f"{city}: {FAKE_WEATHER[city]}"


def calculator(expression: str) -> str:
    allowed = set("0123456789+-*/(). ")
    if not all(c in allowed for c in expression):
        raise ValueError("表达式包含非法字符")
    return str(eval(expression))  # noqa: S307 — 演示用


def search_notes(query: str) -> str:
    return f"找到与『{query}』相关的笔记 3 条（演示数据）"


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        get_weather, "get_weather",
        "查询指定城市的当前天气。城市例：北京、上海、深圳",
        {"type": "object",
         "properties": {"city": {"type": "string", "description": "城市名"}},
         "required": ["city"]},
    )
    reg.register(
        calculator, "calculator",
        "执行算术表达式计算。例如：123*456、 (1+2)*3",
        {"type": "object",
         "properties": {"expression": {"type": "string", "description": "算术表达式"}},
         "required": ["expression"]},
    )
    reg.register(
        search_notes, "search_notes",
        "在个人知识库中搜索笔记。",
        {"type": "object",
         "properties": {"query": {"type": "string", "description": "搜索关键词"}},
         "required": ["query"]},
    )
    return reg
