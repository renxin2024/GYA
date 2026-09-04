#!/usr/bin/env python3
"""C04 学习实验：注册表、结构化错误与有副作用工具的超时恢复。

纯本地、确定性运行：不调用 LLM、订单或支付服务。它验证 Runtime 的工具
管理与恢复边界，不能替代真实 MCP 或生产级持久化实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


class ToolTimeout(Exception):
    """handler 已知本次结果不确定时抛出的超时。"""


class ToolFailure(Exception):
    """非超时的 handler 执行失败。"""


@dataclass(frozen=True)
class ToolResponse:
    status: str
    error_code: str | None = None
    recovery_action: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolDefinition:
    required_arguments: set[str]
    handler_required_arguments: set[str]
    handler: Callable[[dict[str, Any]], ToolResponse]
    enabled: bool = True
    healthy: bool = True
    version: int = 1


class ToolRegistry:
    """只负责工具发现、可用性与参数校验；不拥有领域幂等状态。"""

    def __init__(self) -> None:
        self.tools: dict[str, ToolDefinition] = {}

    def register(self, name: str, required_arguments: set[str],
                 handler_required_arguments: set[str],
                 handler: Callable[[dict[str, Any]], ToolResponse]) -> None:
        """原子更新：候选 schema 与 handler 契约不一致时不覆盖旧版本。"""
        if required_arguments != handler_required_arguments:
            raise ValueError(f"工具 {name} 的 schema 与 handler 输入契约不一致")
        previous = self.tools.get(name)
        version = 1 if previous is None else previous.version + 1
        self.tools[name] = ToolDefinition(
            required_arguments, handler_required_arguments, handler, version=version
        )

    def disable(self, name: str) -> None:
        self.tools[name].enabled = False

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResponse:
        tool = self.tools.get(name)
        if tool is None:
            return ToolResponse("ERROR", "UNKNOWN_TOOL", "DO_NOT_RETRY")
        if not tool.enabled or not tool.healthy:
            return ToolResponse("ERROR", "TOOL_UNAVAILABLE", "DO_NOT_RETRY")
        missing = tool.required_arguments - arguments.keys()
        if missing:
            return ToolResponse(
                "ERROR", "INVALID_ARGUMENT", "DO_NOT_RETRY",
                {"missing": sorted(missing)},
            )
        try:
            return tool.handler(arguments)
        except ToolTimeout:
            return ToolResponse(
                "ERROR", "EXECUTION_ERROR", "CHECK_IDEMPOTENCY_STATUS_FIRST"
            )
        except ToolFailure:
            return ToolResponse("ERROR", "EXECUTION_ERROR", "DO_NOT_RETRY")


class RefundDomain:
    """领域服务模拟：它拥有幂等状态和真实 handler 执行次数。"""

    def __init__(self, timeout_mode: str) -> None:
        self.timeout_mode = timeout_mode
        self.states: dict[str, str] = {}
        self.handler_execution_count = 0
        self.first_call = True

    def refund(self, arguments: dict[str, Any]) -> ToolResponse:
        key = arguments["idempotency_key"]
        if self.timeout_mode == "before_execution" and self.first_call:
            self.first_call = False
            self.states[key] = "NOT_EXECUTED"
            raise ToolTimeout()
        self.handler_execution_count += 1
        self.states[key] = "SUCCEEDED"
        if self.timeout_mode == "after_success" and self.first_call:
            self.first_call = False
            raise ToolTimeout()
        return ToolResponse("SUCCESS", data={"refund_id": "R-100"})

    def query_status(self, key: str) -> str:
        return self.states.get(key, "UNKNOWN")


class Runtime:
    """统一编排恢复，但根据 handler 返回的语义决定是否继续。"""

    def __init__(self, registry: ToolRegistry, refund_domain: RefundDomain) -> None:
        self.registry = registry
        self.refund_domain = refund_domain
        self.trace: list[str] = []

    def refund_with_recovery(self, key: str) -> ToolResponse:
        arguments = {"order_id": "O-100", "idempotency_key": key}
        first = self.registry.execute("refund_order", arguments)
        self.trace.append(f"refund_order response={first.error_code or first.status}")
        if first.recovery_action != "CHECK_IDEMPOTENCY_STATUS_FIRST":
            return first

        state = self.refund_domain.query_status(key)
        self.trace.append(f"idempotency_status={state}")
        if state == "SUCCEEDED":
            self.trace.append("runtime_action=REPLAY_SUCCESS")
            return ToolResponse("SUCCESS", data={"replayed": True})
        if state == "NOT_EXECUTED":
            self.trace.append("runtime_action=RETRY_ONCE")
            return self.registry.execute("refund_order", arguments)
        self.trace.append("runtime_action=WAIT_FOR_RECONCILIATION")
        return ToolResponse("ERROR", "EXECUTION_ERROR", "WAIT_FOR_RECONCILIATION")


def build_registry(domain: RefundDomain) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register("get_weather", {"city"}, {"city"}, lambda _: ToolResponse("SUCCESS"))
    registry.register(
        "refund_order", {"order_id", "idempotency_key"},
        {"order_id", "idempotency_key"}, domain.refund
    )
    registry.register(
        "search_notes", {"query"}, {"query"},
        lambda _: (_ for _ in ()).throw(ToolFailure())
    )
    return registry


def run_demo() -> None:
    domain = RefundDomain("after_success")
    runtime = Runtime(build_registry(domain), domain)
    response = runtime.refund_with_recovery("K-1")
    print("\n".join(runtime.trace))
    print(f"final={response.status}")
    print(f"refund_order handler_execution_count={domain.handler_execution_count}")


if __name__ == "__main__":
    run_demo()
