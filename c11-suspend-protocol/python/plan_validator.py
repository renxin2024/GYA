"""C11 暂停协议：计划校验器。

只检查计划结构，不执行计划、不制造审批结果、不静默修改计划。
它证明「计划结构合法」，不证明「审批已经授予」，也不证明「Run 会停下来」。

计划步骤现在统一是「决定」（带 type 字段）：
- EXECUTE_TOOL：走 ActionGateway。
- REQUEST_USER_INPUT：等待点，不是工具。

必须分清的两件事：
- 计划里**出现过** REQUEST_USER_INPUT，只是结构合法；
- 真正决定停止的是 Runtime：它要把这一步解释成状态迁移，调度器才会退出当前 Run。

ACCEPT / REVISE / REJECT 是本 demo 的错误处理约定，不是行业统一标准：
- ACCEPT：通过了下方列出的静态结构检查。
- REVISE：存在可修订的审批顺序缺口（如 write_draft 前没有 REQUEST_USER_INPUT）。
- REJECT：出现未知决定类型、未知工具或空计划，无法通过补充修复。
"""

from __future__ import annotations

from typing import List, Tuple

from protocol import DecisionType
from tools import ALL_TOOLS

# 受保护写入前必须已经出现的等待点（结构层面）。
REQUIRED_BEFORE = {
    "write_draft": (DecisionType.REQUEST_USER_INPUT.value,),
}


def _decision_type(step: object) -> str:
    if not isinstance(step, dict):
        return ""
    value = step.get("type")
    return value.strip().upper() if isinstance(value, str) else ""


def validate_plan(steps: List[object]) -> Tuple[str, List[str]]:
    """检查一份计划（steps 是决定列表）。"""
    violations: List[str] = []
    if not steps:
        return "REJECT", ["empty_plan"]

    known_types = {member.value for member in DecisionType}
    seen: set = set()
    has_unknown = False

    for index, step in enumerate(steps, start=1):
        decision_type = _decision_type(step)
        if decision_type not in known_types:
            has_unknown = True
            violations.append(f"step-{index}: unknown decision type {decision_type or '<missing>'}")
            continue

        if decision_type == DecisionType.EXECUTE_TOOL.value:
            action = step.get("action") if isinstance(step, dict) else None
            if action not in ALL_TOOLS:
                has_unknown = True
                violations.append(f"step-{index}: unknown action {action}")
                continue
            for required in REQUIRED_BEFORE.get(action, ()):
                if required not in seen:
                    violations.append(f"step-{index}: {action} requires {required} before it")

        seen.add(decision_type)

    if has_unknown:
        return "REJECT", violations
    if violations:
        return "REVISE", violations
    return "ACCEPT", violations
