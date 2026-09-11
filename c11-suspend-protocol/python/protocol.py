"""C11 暂停协议：决定类型、运行状态、待处理请求与状态迁移。

本文件只放数据结构，不含任何业务逻辑，也不依赖模型或工具。
它是全文概念模型在代码里的落点：

- 模型输出的不是「执行结果」，而是候选决定（ControlDecision）。
- 决定有四种类型（DecisionType），Runtime 才知道怎么解释它们。
- Run 的状态是枚举（RunStatus），不是一个布尔标记——
  「等待」是一个状态，不是一个字段。

离线测试可以直接 import 本文件，不需要网络或 API Key。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class DecisionType(Enum):
    """模型/Planner/Workflow 能提出的四种决定。

    提出决定的一方只负责「说要做什么」，不负责它会不会被执行。
    """

    EXECUTE_TOOL = "EXECUTE_TOOL"
    REQUEST_USER_INPUT = "REQUEST_USER_INPUT"
    FINISH = "FINISH"
    FAIL = "FAIL"


class RunStatus(Enum):
    """一次 Run 的状态。

    WAITING_FOR_USER 是本文的主角：它表示当前 Run 已把控制权交还用户。
    它由 Runtime 写入，模型无法直接设置。
    """

    RUNNING = "RUNNING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class ControlDecision:
    """一条候选决定。

    注意字段的可选性：REQUEST_USER_INPUT 用 question，EXECUTE_TOOL 用 action/args。
    同一条类型里的字段缺失是正常输入，不该在解析阶段炸掉——
    校验属于 Runtime 的状态前置条件检查。
    """

    type: DecisionType
    action: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    question: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class PendingRequest:
    """等待中的请求。

    这是「用户回来后该关联哪个请求」的落点：question 是要问用户什么，
    state_before 记录迁移前的状态（C11 只到这一步；跨进程恢复属于 C12）。
    """

    request_id: str
    question: str
    state_before: str


@dataclass
class Transition:
    """Runtime 对一条决定的裁决结果。

    kind 回答「调度该怎么办」：继续循环、挂起、完成、失败。
    """

    kind: str  # CONTINUE / SUSPEND / COMPLETE / FAIL
    status: RunStatus
    note: str = ""


@dataclass
class TraceEvent:
    """一次决定、一次校验或一次迁移的最小记录。

    前六个字段是本文的 Trace 契约（任务书第十三节），
    后六个字段用于回答「信号是谁产生的、Runtime 怎样解释、状态怎样变化」。
    """

    # Trace 契约
    run_id: str = "run_001"
    step: int = 0
    signal_source: Optional[str] = None
    signal_type: Optional[str] = None
    runtime_decision: Optional[str] = None
    state_before: Optional[str] = None
    state_after: Optional[str] = None
    pending_request_id: Optional[str] = None
    model_calls_after_wait: Optional[int] = None
    tool_calls_after_wait: Optional[int] = None

    # 演示用字段：谁做的决定、发生了什么、结果是什么
    mode: str = ""
    decision_maker: str = ""
    event: str = ""
    action: Optional[str] = None
    result: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        """输出时丢掉空字段，避免 Trace 被 null 淹没。"""
        return {
            key: value
            for key, value in self.__dict__.items()
            if value is not None and value != ""
        }


@dataclass
class ModeResult:
    """一次运行的结果。

    model_calls_after_wait / tool_calls_after_wait 是「Run 真的停了吗」的证据：
    它们必须在等待之后保持为 0。
    """

    mode: str
    final_state: "RunState"  # noqa: F821  (见 state.py，避免循环导入)
    trace: List[TraceEvent] = field(default_factory=list)
    terminal_reason: str = ""
    model_calls_after_wait: int = 0
    tool_calls_after_wait: int = 0
    plan_status: Optional[str] = None
    plan_violations: List[str] = field(default_factory=list)
