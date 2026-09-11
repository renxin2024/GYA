"""C11 暂停协议：CLI 入口。

默认跑离线夹具（不需要 API Key）：
三种控制器（ReAct / Planner / Workflow）各自提出等待信号，全部交给同一个 Runtime。

--naive 跑缺陷版：同一批控制器换成一个没有 Runtime 的循环，
用来对照「信号产生了，循环却没有停」。

--live 跑真实模型（需要 LLM_API_URL + LLM_MODEL + LLM_API_KEY/DEEPSEEK_API_KEY）。
--no-follow-up 关闭 material_1 的 follow_up 线索，用来验证 Workflow 的分支是真条件分支。

每种控制器使用独立的 client / gateway / store，避免产物与统计泄漏。
"""

from __future__ import annotations

import argparse
import json
from typing import Callable, List

from controllers import PlannerController, ReactController, WorkflowController
from llm import FixtureLlmClient, LlmClient, RealLlmClient
from protocol import ModeResult
from scheduler import run_naive, run_with_runtime
from state import VirtualStore
from tools import ActionGateway


def _print_trace(result: ModeResult) -> None:
    for event in result.trace:
        print("[trace] " + json.dumps(event.as_dict(), ensure_ascii=False))


def _print_summary(result: ModeResult) -> None:
    state = result.final_state
    summary = {
        "mode": result.mode,
        "terminal_reason": result.terminal_reason,
        "status": state.status.value,
        "pending_request_id": state.pending.request_id if state.pending else None,
        "brief_created": state.brief_created,
        "draft_written": state.draft_written,
        "approval_granted": state.approval_granted,
        "waiting_marker": state.waiting_marker,
        "model_calls": state.model_calls,
        "tool_attempts": state.tool_attempts,
        "tool_successes": state.tool_successes,
        "rejected_actions": state.rejected_actions,
        "rejected_signals": state.rejected_signals,
        "model_calls_after_wait": result.model_calls_after_wait,
        "tool_calls_after_wait": result.tool_calls_after_wait,
        "plan_status": result.plan_status,
        "usage": state.usage,
    }
    print("[summary] " + json.dumps(summary, ensure_ascii=False))


def _build_runs(
    client_factory: Callable[[], LlmClient],
) -> List[tuple]:
    """每个控制器配一个自己的 client。

    控制器用这个 client 提出决定，调度循环用**同一个** client 统计调用数。
    若两边各建一个 client，循环读到的 calls 会恒为 0，
    「等待之后没有新调用」这条证据就失效了。
    """
    runs: List[tuple] = []
    for factory in (ReactController, PlannerController, WorkflowController):
        client = client_factory()
        runs.append((factory(client), client))
    return runs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="调用真实 LLM")
    parser.add_argument(
        "--naive",
        action="store_true",
        help="跑没有 Runtime 的缺陷版循环（对照：信号产生了，循环没停）",
    )
    parser.add_argument(
        "--no-follow-up",
        action="store_true",
        help="关闭 material_1 的 follow_up 线索，验证 Workflow 分支是真条件分支",
    )
    args = parser.parse_args()

    client_factory: Callable[[], LlmClient] = RealLlmClient if args.live else FixtureLlmClient

    results: List[ModeResult] = []
    for controller, client in _build_runs(client_factory):
        store = VirtualStore()
        gateway = ActionGateway(store, follow_up_enabled=not args.no_follow_up)
        if args.naive:
            results.append(run_naive(controller, client, gateway, mark_waiting=True))
        else:
            results.append(run_with_runtime(controller, client, gateway))

    for result in results:
        _print_trace(result)
        _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
