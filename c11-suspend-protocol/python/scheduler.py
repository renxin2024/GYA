"""C11 暂停协议：调度循环。

两种循环放在同一个文件里，因为它们的差别只在一处：

- `run_with_runtime`：控制器提出决定 → Runtime 解析并迁移 → 调度器按结果继续或退出。
- `run_naive`：没有 Runtime。模型输出被直接当成要做的事，等待信号被当成一条数据。

两者共用同一个控制器、同一套工具、同一份状态结构。
所以「停不停」不是模式差异，而是循环里有没有 Runtime —— 这是本文最关键的一条判断。
"""

from __future__ import annotations

from typing import List, Optional

from controllers import Controller
from llm import LlmClient
from protocol import DecisionType, ModeResult, RunStatus, TraceEvent
from runtime import RUN_ID, Runtime
from state import RunState
from tools import ActionGateway

DEFAULT_MAX_STEPS = 8


def _sync_stats(client: LlmClient, state: RunState) -> None:
    state.model_calls = client.calls
    state.usage = client.usage


def _finish(
    mode: str,
    state: RunState,
    trace: List[TraceEvent],
    terminal_reason: str,
    plan_status: Optional[str] = None,
    plan_violations: Optional[List[str]] = None,
) -> ModeResult:
    model_after, tool_after = state.calls_after_wait()
    return ModeResult(
        mode=mode,
        final_state=state,
        trace=trace,
        terminal_reason=terminal_reason,
        model_calls_after_wait=model_after,
        tool_calls_after_wait=tool_after,
        plan_status=plan_status,
        plan_violations=plan_violations or [],
    )


def run_with_runtime(
    controller: Controller,
    client: LlmClient,
    gateway: ActionGateway,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> ModeResult:
    """带 Runtime 的调度循环。

    控制器只提出决定；要不要继续跑，由 Runtime 的状态迁移结果决定。
    """
    state = RunState()
    trace: List[TraceEvent] = []
    runtime = Runtime(gateway)
    plan_status: Optional[str] = None
    plan_violations: List[str] = []
    terminal_reason = ""

    step = 0
    while step < max_steps:
        if state.status is not RunStatus.RUNNING:
            break
        step += 1

        raw = controller.propose(state, step)
        # 立刻把调用计数同步进状态：等待快照要记的是「此刻真实发生过的调用数」。
        # 若只在循环结束时同步，model_calls_at_wait 会是 0，
        # 等待后的增量就会被算成全部调用，判据反而证明不了「停下」。
        _sync_stats(client, state)

        # 计划校验只检查结构，不产生审批结果。REJECT 时明确失败，不硬跑下去。
        if plan_status is None and getattr(controller, "plan_status", None) is not None:
            plan_status = controller.plan_status
            plan_violations = list(getattr(controller, "plan_violations", []) or [])
            trace.append(
                TraceEvent(
                    run_id=RUN_ID,
                    step=step,
                    mode=controller.name,
                    decision_maker="plan_validator",
                    event="validate_plan",
                    result=plan_status,
                )
            )
            if plan_status == "REJECT":
                state.status = RunStatus.FAILED
                terminal_reason = "plan_rejected"
                break

        # 步骤 1-2：解析 + 类型校验。无法解释的输出不让它悄悄过去。
        decision = runtime.parse(raw)
        if decision is None:
            state.rejected_signals += 1
            state_before = state.status.value
            state.status = RunStatus.FAILED
            trace.append(
                TraceEvent(
                    run_id=RUN_ID,
                    step=step,
                    signal_source=controller.signal_source,
                    runtime_decision="REJECT_SIGNAL",
                    state_before=state_before,
                    state_after=state.status.value,
                    mode=controller.name,
                    decision_maker="runtime",
                    event="parse_failed",
                    result="unparseable_decision: " + str(raw)[:160],
                )
            )
            terminal_reason = "parse_failed"
            break

        # 步骤 3-5：前置条件校验 → 迁移与记录 → 返回
        transition = runtime.handle(
            decision, state, trace, controller.name, step, controller.signal_source
        )

        if transition.kind == "SUSPEND":
            _sync_stats(client, state)
            state_after = state.status.value
            model_after, tool_after = state.calls_after_wait()
            trace.append(
                TraceEvent(
                    run_id=RUN_ID,
                    step=step,
                    signal_source=controller.signal_source,
                    signal_type=DecisionType.REQUEST_USER_INPUT.value,
                    runtime_decision="SUSPEND_RUN",
                    state_before=state_after,
                    state_after=state_after,
                    pending_request_id=state.pending.request_id if state.pending else None,
                    model_calls_after_wait=model_after,
                    tool_calls_after_wait=tool_after,
                    mode=controller.name,
                    decision_maker="scheduler",
                    event="run_exited",
                    result="control_returned_to_caller",
                )
            )
            terminal_reason = "wait_suspended"
            break

        if transition.kind == "CONTINUE":
            if decision.type is DecisionType.EXECUTE_TOOL:
                controller.on_tool_result(transition.note)
            continue

        # COMPLETE / FAIL
        terminal_reason = "completed" if transition.kind == "COMPLETE" else transition.note
        break
    else:
        # 循环没有被 break，说明步数预算耗尽
        if state.status is RunStatus.RUNNING:
            terminal_reason = "budget_exhausted"

    _sync_stats(client, state)
    return _finish(
        controller.name, state, trace, terminal_reason, plan_status, plan_violations
    )


def run_naive(
    controller: Controller,
    client: LlmClient,
    gateway: ActionGateway,
    max_steps: int = DEFAULT_MAX_STEPS,
    mark_waiting: bool = False,
) -> ModeResult:
    """缺陷版：循环里没有 Runtime。

    它把模型输出直接当成「要做的事」，等待信号被当成一条数据：
    - mark_waiting=False：连标记都不记，直接继续下一轮。
    - mark_waiting=True：把等待记成一个数据标记（state.waiting_marker）然后继续。

    两种写法都**没有**停止调度。这正是「waiting=true 不等于循环已经停止」的最小复现。
    注意：它不是「另一种模式」，而是同一个控制器换了一个没有 Runtime 的消费方。
    """
    state = RunState()
    trace: List[TraceEvent] = []
    terminal_reason = ""

    step = 0
    while step < max_steps:
        step += 1
        raw = controller.propose(state, step)
        decision_type = raw.get("type") if isinstance(raw, dict) else None

        if decision_type == DecisionType.EXECUTE_TOOL.value:
            action = raw.get("action") or ""
            args = raw.get("args") or {}
            result = gateway.execute(action, args, state)
            trace.append(
                TraceEvent(
                    run_id=RUN_ID,
                    step=step,
                    state_before=state.status.value,
                    state_after=state.status.value,
                    mode=controller.name,
                    decision_maker="naive_loop",
                    event="tool_executed_without_runtime",
                    action=action,
                    result=result,
                )
            )
            controller.on_tool_result(result)
            continue

        if decision_type == DecisionType.REQUEST_USER_INPUT.value:
            if mark_waiting:
                state.waiting_marker = True
            trace.append(
                TraceEvent(
                    run_id=RUN_ID,
                    step=step,
                    signal_source=controller.signal_source,
                    signal_type=decision_type,
                    state_before=state.status.value,
                    state_after=state.status.value,
                    mode=controller.name,
                    decision_maker="naive_loop",
                    event="wait_ignored",
                    action=decision_type,
                    result=data_marker_note(mark_waiting),
                )
            )
            continue

        if decision_type == DecisionType.FINISH.value:
            state_before = state.status.value
            state.status = RunStatus.COMPLETED
            trace.append(
                TraceEvent(
                    run_id=RUN_ID,
                    step=step,
                    state_before=state_before,
                    state_after=state.status.value,
                    mode=controller.name,
                    decision_maker="naive_loop",
                    event="finish_without_runtime",
                    result="completed",
                )
            )
            terminal_reason = "completed"
            break

        # 无法识别的输出：同样被忽略，循环继续。
        trace.append(
            TraceEvent(
                run_id=RUN_ID,
                step=step,
                state_before=state.status.value,
                state_after=state.status.value,
                mode=controller.name,
                decision_maker="naive_loop",
                event="decision_ignored",
                result=str(raw)[:80],
            )
        )
        continue
    else:
        if state.status is RunStatus.RUNNING:
            terminal_reason = "budget_exhausted"

    _sync_stats(client, state)
    return _finish(controller.name, state, trace, terminal_reason)


def data_marker_note(mark_waiting: bool) -> str:
    return "waiting_marker=True; loop_continues" if mark_waiting else "loop_continues"
