#!/usr/bin/env python3
"""C05 成文 demo：从单次工具调用扩展为最小 ReAct Runtime。

真实 LLM 只选择下一步候选 Action；地址和天气是确定性、只读夹具。
这让 live Trace 证明模型是否依据 Observation 改变后续调用，而离线测试
可以稳定覆盖 Runtime 状态机。不要把这两个层面的证据混为一谈。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    WAITING_FOR_CLARIFICATION = "WAITING_FOR_CLARIFICATION"
    COMPLETED = "COMPLETED"
    MAX_STEPS = "MAX_STEPS"


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str = "local-call"


@dataclass
class ModelTurn:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class Model(Protocol):
    def decide(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn: ...


class ToolRegistry:
    """工具及参数契约边界：这里拒绝坏参数，不让 handler 抛异常中断 Run。"""

    REQUIRED = {
        "resolve_company_address": ("company_name",),
        "get_weather": ("city",),
        "request_clarification": ("question", "missing_field"),
    }

    def schemas(self) -> list[dict[str, Any]]:
        return [
            self._schema("resolve_company_address", "解析公司总部名称，返回唯一城市或 AMBIGUOUS", "company_name"),
            self._schema("get_weather", "查询已解析城市的天气", "city"),
            self._schema("request_clarification", "信息不足时请求补充；调用后 Run 暂停", "question", "missing_field"),
        ]

    @staticmethod
    def _schema(name: str, description: str, *required: str) -> dict[str, Any]:
        return {"type": "function", "function": {"name": name, "description": description,
                "parameters": {"type": "object", "properties": {key: {"type": "string"} for key in required}, "required": list(required)}}}

    def execute(self, call: ToolCall) -> dict[str, Any]:
        required = self.REQUIRED.get(call.name)
        if required is None:
            return {"status": "ERROR", "code": "UNKNOWN_TOOL"}
        invalid = [key for key in required if not isinstance(call.arguments.get(key), str) or not call.arguments[key].strip()]
        if invalid:
            return {"status": "ERROR", "code": "INVALID_ARGUMENT", "missing_or_invalid": invalid}
        return getattr(self, call.name)(**call.arguments)

    @staticmethod
    def resolve_company_address(company_name: str) -> dict[str, Any]:
        if company_name in {"上海总部", "上海总部地址"}:
            return {"status": "RESOLVED", "city": "上海"}
        if company_name in {"北京总部", "北京总部地址"}:
            return {"status": "RESOLVED", "city": "北京"}
        return {"status": "AMBIGUOUS", "message": "请补充公司名称或所在城市"}

    @staticmethod
    def get_weather(city: str) -> dict[str, Any]:
        return {"status": "SUCCESS", "city": city, "weather": {"上海": "小雨，22℃", "北京": "晴，18℃"}.get(city, "未知")}

    @staticmethod
    def request_clarification(question: str, missing_field: str) -> dict[str, Any]:
        return {"status": "WAITING_FOR_CLARIFICATION", "question": question, "missing_field": missing_field}


@dataclass
class AgentState:
    messages: list[dict[str, Any]]
    trace: list[str] = field(default_factory=list)
    status: RunStatus = RunStatus.RUNNING
    resolved_city: str | None = None
    pending_clarification: str | None = None


class ReactRuntime:
    """模型提议 Action；Runtime 组织历史、校验状态、执行工具并决定是否停止。"""

    def __init__(self, model: Model, registry: ToolRegistry | None = None) -> None:
        self.model, self.registry = model, registry or ToolRegistry()

    def start(self, question: str, max_steps: int = 4) -> AgentState:
        return self._drive(AgentState(messages=[{"role": "user", "content": question}]), max_steps)

    def resume(self, state: AgentState, clarification: str, max_steps: int = 4) -> AgentState:
        if state.status is not RunStatus.WAITING_FOR_CLARIFICATION:
            raise ValueError("only a waiting run can resume")
        state.messages.append({"role": "user", "content": f"补充信息：{clarification}"})
        state.trace.append("external_input=clarification")
        state.status, state.pending_clarification = RunStatus.RUNNING, None
        return self._drive(state, max_steps)

    def _drive(self, state: AgentState, max_steps: int) -> AgentState:
        for step in range(1, max_steps + 1):
            turn = self.model.decide(state.messages, self.registry.schemas())
            call = turn.tool_calls[0] if turn.tool_calls else None
            candidate = f"{call.name}{json.dumps(call.arguments, ensure_ascii=False)}" if call else "FINAL"
            state.trace.append(f"step={step} model_candidate={candidate}")
            if call is None:
                state.messages.append({"role": "assistant", "content": turn.content or ""})
                state.trace.append(f"model_final={(turn.content or '')[:160]}")
                state.status = RunStatus.WAITING_FOR_CLARIFICATION if state.pending_clarification else RunStatus.COMPLETED
                return state

            rejection = self._guard(call, state)
            if rejection:
                state.trace.append(f"runtime_reject={rejection}")
                state.status = RunStatus.WAITING_FOR_CLARIFICATION
                return state

            # 这条 assistant 历史会随下一轮请求发送；缺少 type=function 时，服务端会在
            # 第二轮校验协议并拒绝请求。因此它由 Runtime 负责，不能期待模型代为补齐。
            state.messages.append({"role": "assistant", "tool_calls": [{"id": call.call_id, "type": "function", "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)}}]})
            observation = self.registry.execute(call)
            state.trace.extend([f"runtime_execute={call.name}{json.dumps(call.arguments, ensure_ascii=False)}", f"observation={call.name}:{observation['status']}"])
            state.messages.append({"role": "tool", "tool_call_id": call.call_id, "content": json.dumps(observation, ensure_ascii=False)})
            if call.name == "resolve_company_address" and observation["status"] == "RESOLVED":
                state.resolved_city = observation["city"]
            elif call.name == "resolve_company_address" and observation["status"] == "AMBIGUOUS":
                state.pending_clarification = observation["message"]
            if call.name == "request_clarification":
                state.pending_clarification, state.status = observation["question"], RunStatus.WAITING_FOR_CLARIFICATION
                state.trace.append(f"runtime_wait=missing:{observation['missing_field']}")
                return state
        state.status = RunStatus.MAX_STEPS
        state.trace.append("runtime_stop=MAX_STEPS")
        return state

    @staticmethod
    def _guard(call: ToolCall, state: AgentState) -> str | None:
        city = call.arguments.get("city")
        if state.pending_clarification and call.name != "request_clarification":
            return "WAITING_FOR_CLARIFICATION"
        if call.name == "get_weather" and isinstance(city, str) and city and city != state.resolved_city:
            return "WEATHER_MUST_USE_RESOLVED_CITY"
        return None


class OpenAICompatibleModel:
    SYSTEM = """你是工具调用 Agent。查询总部天气时先调用 resolve_company_address；RESOLVED 后只能使用返回的 city 调 get_weather。地址歧义或缺失时调用 request_clarification，missing_field=company_name。本实验中“上海总部”和“北京总部”都是合法的 company_name。收到以“补充信息：”开头的用户消息时，值就是 company_name，必须立即解析，不能再次澄清。不得猜测城市或用自然语言代替澄清 Action。"""

    def __init__(self) -> None:
        self.url = os.environ["LLM_API_URL"]
        self.key = os.environ["LLM_API_KEY"]
        self.model = os.environ["LLM_MODEL"]

    def decide(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn:
        payload = {"model": self.model, "messages": [{"role": "system", "content": self.SYSTEM}, *messages], "tools": tools, "stream": False}
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        with urllib.request.urlopen(request, timeout=60) as response:
            message = json.loads(response.read())["choices"][0]["message"]
        calls = [ToolCall(item["function"]["name"], json.loads(item["function"]["arguments"] or "{}"), item["id"]) for item in message.get("tool_calls", [])]
        return ModelTurn(message.get("content"), calls)


def print_state(state: AgentState) -> None:
    print("\n".join(state.trace))
    print(f"status={state.status.value}")


def main() -> None:
    runtime = ReactRuntime(OpenAICompatibleModel())
    state = runtime.start("查询公司总部今天的天气")
    print_state(state)
    if state.status is RunStatus.WAITING_FOR_CLARIFICATION:
        print("--- resumed ---")
        print_state(runtime.resume(state, "北京总部"))


if __name__ == "__main__":
    main()
