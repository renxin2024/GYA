"""C11 暂停协议：Runtime —— 唯一拥有状态迁移权的组件。

这篇文章的核心结论落在这个文件里：

    模型不能暂停程序。模型只能产生候选决定；
    Runtime 负责解析它、校验当前状态是否允许它、执行状态迁移，
    并告诉调度器「继续、挂起、完成还是失败」。

`Runtime.parse()` 做解析与类型校验（步骤 1-2）；
`Runtime.handle()` 做状态前置条件校验、迁移与记录（步骤 3-5）。
控制器（ReAct / Planner / Workflow）没有状态迁移权，只能提出决定。
"""

from __future__ import annotations

from typing import List, Optional

from protocol import (
    ControlDecision,
    DecisionType,
    ModeResult,
    PendingRequest,
    RunStatus,
    TraceEvent,
    Transition,
)
from state import RunState
from tools import ALL_TOOLS, ActionGateway

# 一次等待在 Trace 里必须留下的五类事件，按顺序出现。
# Python 与 Java 的关键事件类型与顺序必须一致（不要求字段顺序一致）。
RUNTIME_EVENT_ORDER = (
    "signal_received",
    "runtime_validated",
    "state_transition",
    "pending_recorded",
    "run_exited",
)

RUN_ID = "run_001"


class Runtime:
    """决定「当前 Run 要不要继续」的那一层。"""

    def __init__(self, gateway: ActionGateway) -> None:
        self.gateway = gateway
        self._pending_seq = 0

    # ── 步骤 1-2：解析 + 类型校验 ──────────────────────────────────────

    def parse(self, raw: object) -> Optional[ControlDecision]:
        """把模型/Planner/Workflow 的原始输出解析成 ControlDecision。

        返回 None 表示「Runtime 无法解释这条输出」：
        不是合法对象、没有 type 字段、或 type 不在四种已知决定里。
        自然语言（例如「请用户确认」）在这里就会失败——
        它不是机器可识别的等待信号。解析失败不静默当成正常动作，
        而是让 Run 以明确失败结束。
        """
        if not isinstance(raw, dict):
            return None
        type_value = raw.get("type")
        if not isinstance(type_value, str):
            return None
        try:
            decision_type = DecisionType(type_value.strip().upper())
        except ValueError:
            return None
        args = raw.get("args")
        return ControlDecision(
            type=decision_type,
            action=raw.get("action"),
            args=args if isinstance(args, dict) else {},
            question=raw.get("question"),
            reason=raw.get("reason"),
        )

    # ── 步骤 3-5：前置条件校验 → 迁移与记录 → 返回 ────────────────────

    def handle(
        self,
        decision: ControlDecision,
        state: RunState,
        trace: List[TraceEvent],
        mode: str,
        step: int,
        signal_source: str,
    ) -> Transition:
        state_before = state.status.value
        trace.append(
            TraceEvent(
                run_id=RUN_ID,
                step=step,
                signal_source=signal_source,
                signal_type=decision.type.value,
                state_before=state_before,
                mode=mode,
                decision_maker=signal_source,
                event="signal_received",
            )
        )

        # 步骤 3：状态前置条件校验
        refusal = self._check_precondition(decision, state)
        if refusal is not None:
            return self._refuse(decision, state, trace, mode, step, refusal)

        trace.append(
            TraceEvent(
                run_id=RUN_ID,
                step=step,
                signal_type=decision.type.value,
                runtime_decision="ACCEPT_SIGNAL",
                state_before=state_before,
                state_after=state_before,
                mode=mode,
                decision_maker="runtime",
                event="runtime_validated",
                result="accepted",
            )
        )

        # 步骤 4：迁移与记录
        if decision.type is DecisionType.EXECUTE_TOOL:
            result = self.gateway.execute(decision.action or "", decision.args or {}, state)
            trace.append(
                TraceEvent(
                    run_id=RUN_ID,
                    step=step,
                    state_before=state_before,
                    state_after=state.status.value,
                    mode=mode,
                    decision_maker="runtime",
                    event="tool_executed",
                    action=decision.action,
                    result=result,
                )
            )
            return Transition("CONTINUE", state.status, result)

        if decision.type is DecisionType.REQUEST_USER_INPUT:
            self._pending_seq += 1
            pending = PendingRequest(
                request_id=f"approval_{self._pending_seq:03d}",
                question=(decision.question or "").strip(),
                state_before=state_before,
            )
            state.pending = pending
            state.status = RunStatus.WAITING_FOR_USER
            # 快照必须在迁移的同一时刻记下，否则无法证明「等待之后没有新调用」。
            state.snapshot_wait()
            trace.append(
                TraceEvent(
                    run_id=RUN_ID,
                    step=step,
                    signal_type=decision.type.value,
                    runtime_decision="SUSPEND_RUN",
                    state_before=state_before,
                    state_after=state.status.value,
                    mode=mode,
                    decision_maker="runtime",
                    event="state_transition",
                    result="run_suspended",
                )
            )
            trace.append(
                TraceEvent(
                    run_id=RUN_ID,
                    step=step,
                    state_before=state.status.value,
                    state_after=state.status.value,
                    pending_request_id=pending.request_id,
                    mode=mode,
                    decision_maker="runtime",
                    event="pending_recorded",
                    action=decision.type.value,
                    result=("question=" + pending.question) if pending.question else "question=",
                )
            )
            return Transition("SUSPEND", state.status, "run_suspended")

        if decision.type is DecisionType.FINISH:
            state.status = RunStatus.COMPLETED
            trace.append(
                self._transition_event(step, state_before, state, mode, "FINISH")
            )
            return Transition("COMPLETE", state.status, "completed")

        # DecisionType.FAIL
        state.status = RunStatus.FAILED
        trace.append(self._transition_event(step, state_before, state, mode, "FAIL"))
        return Transition("FAIL", state.status, decision.reason or "controller_failed")

    # ── 内部工具 ──────────────────────────────────────────────────────

    def _check_precondition(
        self, decision: ControlDecision, state: RunState
    ) -> Optional[str]:
        """状态前置条件：当前状态允不允许这条决定。

        这一层就是「非法状态下的等待信号」被拒绝的地方。
        没有它，模型可以在任何时刻宣称「我要等用户」——
        而那时根本没有等待的对象。
        """
        if decision.type is DecisionType.EXECUTE_TOOL:
            if decision.action not in ALL_TOOLS:
                return f"unknown_action: {decision.action}"
            return None

        if decision.type is DecisionType.REQUEST_USER_INPUT:
            if not state.brief_created:
                # 还没有「等待用户确认」的对象，这条等待信号不合法。
                return "wait_signal_without_pending_object"
            if not (decision.question or "").strip():
                return "wait_signal_without_question"
            return None

        if decision.type is DecisionType.FINISH:
            if not state.brief_created:
                # 模型宣称完成，但任务没满足：运行时拒绝把未完成任务标成完成。
                return "premature_finish"
            return None

        return None

    def _refuse(
        self,
        decision: ControlDecision,
        state: RunState,
        trace: List[TraceEvent],
        mode: str,
        step: int,
        reason: str,
    ) -> Transition:
        """拒绝一条决定。

        两类后果必须区分：
        - 等待信号不合法 → Run 明确失败（不是「悄悄继续」）。
        - 工具动作不合法 / 过早完成 → 拒绝这一条，Run 继续跑（模型还有机会纠正）。
        """
        trace.append(
            TraceEvent(
                run_id=RUN_ID,
                step=step,
                signal_type=decision.type.value,
                runtime_decision="REJECT_SIGNAL",
                state_before=state.status.value,
                state_after=state.status.value,
                mode=mode,
                decision_maker="runtime",
                event="runtime_validated",
                action=decision.action,
                result=reason,
            )
        )

        if decision.type is DecisionType.REQUEST_USER_INPUT:
            state.rejected_signals += 1
            state_before = state.status.value
            state.status = RunStatus.FAILED
            trace.append(
                self._transition_event(step, state_before, state, mode, "RUN_TO_FAILED")
            )
            return Transition("FAIL", state.status, reason)

        state.rejected_actions += 1
        return Transition("CONTINUE", state.status, reason)

    @staticmethod
    def _transition_event(
        step: int, state_before: str, state: RunState, mode: str, label: str
    ) -> TraceEvent:
        return TraceEvent(
            run_id=RUN_ID,
            step=step,
            runtime_decision=label,
            state_before=state_before,
            state_after=state.status.value,
            mode=mode,
            decision_maker="runtime",
            event="state_transition",
            result=state.status.value,
        )


def is_run_suspended(result: ModeResult) -> bool:
    """「Run 真的停了吗」的可复用判据。

    四个条件同时成立才算停：
    1. 状态是 WAITING_FOR_USER（不是某个布尔标记为真）；
    2. 等待之后没有新的模型调用；
    3. 等待之后没有新的工具尝试；
    4. Run 的状态里留下了对应的 pending request。

    缺陷版会在这条判据上失败——这正是它被测试发现的方式。
    """
    state = result.final_state
    model_delta, tool_delta = state.calls_after_wait()
    return (
        state.status is RunStatus.WAITING_FOR_USER
        and state.pending is not None
        and model_delta == 0
        and tool_delta == 0
    )


def wait_event_sequence(trace: List[TraceEvent]) -> List[str]:
    """抽出「一次等待」留下的事件序列，用于顺序断言与跨语言对照。

    取 run_exited 往前最近的一段：从它前面最近的 signal_received 开始到 run_exited 结束。
    这样三种信号来源（llm / planner / workflow）得到的序列都应该是同样五类事件。
    """
    if not trace:
        return []
    exit_index = max(
        (index for index, event in enumerate(trace) if event.event == "run_exited"),
        default=-1,
    )
    if exit_index < 0:
        return []
    start = exit_index
    while start > 0 and trace[start].event != "signal_received":
        start -= 1
    return [event.event for event in trace[start : exit_index + 1]]
