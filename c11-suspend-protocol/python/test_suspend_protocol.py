"""C11 暂停协议：离线测试。

覆盖两件事：
1. 验收矩阵的十项语义（等待迁移、等待后无调用、Gateway 拦截不等于暂停、
   非法状态拒绝、pending 字段、三条信号来源共用同一 Runtime、Trace 契约）。
2. 本次重构修正的两处问题（提示词不得硬编码资料顺序、Workflow 分支必须是真条件分支）。

全部离线运行，不需要网络或 API Key。
"""

from __future__ import annotations

import unittest
from typing import List, Sequence

from controllers import (
    PlannerController,
    ReactController,
    ScriptedController,
    WorkflowController,
)
from llm import FixtureLlmClient
from plan_validator import validate_plan
from protocol import DecisionType, ModeResult, RunStatus
from runtime import RUNTIME_EVENT_ORDER, Runtime, is_run_suspended, wait_event_sequence
from scheduler import run_naive, run_with_runtime
from state import VISIBLE_MATERIALS, VirtualStore
from tools import ActionGateway

BRIEF = {
    "type": "EXECUTE_TOOL",
    "action": "create_brief",
    "args": {"content": "纲领正文", "evidence_ids": ["material_1"]},
}
WAIT = {"type": "REQUEST_USER_INPUT", "question": "是否继续生成正文草稿？"}
WRITE = {"type": "EXECUTE_TOOL", "action": "write_draft", "args": {"content": "正文草稿"}}


class ProtocolCase(unittest.TestCase):
    """共用装配：每次运行都新建 client / gateway / store，避免产物与统计泄漏。"""

    def run_scripted(
        self, decisions: Sequence[dict], max_steps: int = 8
    ) -> tuple:
        client = FixtureLlmClient()
        store = VirtualStore()
        gateway = ActionGateway(store)
        result = run_with_runtime(
            ScriptedController(list(decisions)), client, gateway, max_steps=max_steps
        )
        return result, store, client

    def run_naive_scripted(
        self,
        decisions: Sequence[dict],
        max_steps: int = 4,
        mark_waiting: bool = False,
    ) -> tuple:
        client = FixtureLlmClient()
        store = VirtualStore()
        gateway = ActionGateway(store)
        result = run_naive(
            ScriptedController(list(decisions)),
            client,
            gateway,
            max_steps=max_steps,
            mark_waiting=mark_waiting,
        )
        return result, store, client

    def assert_run_suspended(self, result: ModeResult) -> None:
        """可复用的判据：状态是 WAITING、有 pending、且等待后没有新调用。"""
        state = result.final_state
        self.assertTrue(
            is_run_suspended(result),
            "Run 没有真正停下：status={} pending={} after_wait=({}, {})".format(
                state.status.value,
                state.pending.request_id if state.pending else None,
                result.model_calls_after_wait,
                result.tool_calls_after_wait,
            ),
        )


# ── 验收矩阵 1：自然语言不是等待信号 ────────────────────────────────────


class TestSignalIsNotControlFlow(ProtocolCase):
    def test_natural_language_is_not_a_wait_signal(self):
        runtime = Runtime(ActionGateway(VirtualStore()))
        self.assertIsNone(runtime.parse("请用户确认"), "自然语言不该被解析成决定")
        self.assertIsNone(runtime.parse({"type": "WAIT_FOR_USER"}), "未知类型应解析失败")
        self.assertIsNone(runtime.parse({"action": "read_material"}), "缺少 type 应解析失败")
        decision = runtime.parse({"type": "request_user_input", "question": "继续吗？"})
        self.assertIsNotNone(decision)
        self.assertIs(decision.type, DecisionType.REQUEST_USER_INPUT)

    def test_wait_signal_alone_does_not_stop_naive_loop(self):
        client = FixtureLlmClient()
        store = VirtualStore()
        result = run_naive(
            ReactController(client), client, ActionGateway(store), max_steps=8
        )
        state = result.final_state
        # 模型提出过等待信号，但循环没有识别它：状态从未进入等待。
        self.assertIn(
            "wait_ignored", [event.event for event in result.trace], "缺陷版应记下被忽略的等待"
        )
        self.assertIs(state.status, RunStatus.RUNNING)
        self.assertEqual(result.terminal_reason, "budget_exhausted")
        self.assertEqual(state.model_calls, 8, "等待信号之后仍在继续调用模型")
        self.assertFalse(is_run_suspended(result))


# ── 验收矩阵 2、8：Runtime 迁移与 pending 记录 ──────────────────────────


class TestRuntimeMigration(ProtocolCase):
    def test_request_user_input_moves_run_to_waiting(self):
        result, _store, _client = self.run_scripted([BRIEF, WAIT])
        self.assertIs(result.final_state.status, RunStatus.WAITING_FOR_USER)
        self.assertEqual(result.terminal_reason, "wait_suspended")

    def test_pending_request_records_question_id_and_state_before(self):
        result, _store, _client = self.run_scripted([BRIEF, WAIT])
        pending = result.final_state.pending
        self.assertIsNotNone(pending)
        self.assertEqual(pending.request_id, "approval_001")
        self.assertEqual(pending.question, WAIT["question"])
        self.assertEqual(pending.state_before, "RUNNING")
        # pending 同时要出现在 Trace 里，用户回来时才有关联标识。
        exit_event = [e for e in result.trace if e.event == "run_exited"][0]
        self.assertEqual(exit_event.pending_request_id, "approval_001")


# ── 验收矩阵 3、4：等待之后没有新调用 ──────────────────────────────────


class TestStoppedProof(ProtocolCase):
    def test_no_model_calls_after_wait(self):
        result, _store, _client = self.run_scripted([BRIEF, WAIT, WRITE])
        self.assertEqual(result.model_calls_after_wait, 0)
        self.assertEqual(
            result.final_state.model_calls, result.final_state.model_calls_at_wait
        )

    def test_no_tool_calls_after_wait(self):
        result, _store, _client = self.run_scripted([BRIEF, WAIT, WRITE])
        self.assertEqual(result.tool_calls_after_wait, 0)
        self.assertEqual(
            result.final_state.tool_attempts, result.final_state.tool_attempts_at_wait
        )

    def test_run_returns_to_caller(self):
        result, _store, _client = self.run_scripted([BRIEF, WAIT, WRITE])
        self.assert_run_suspended(result)
        exit_event = result.trace[-1]
        self.assertEqual(exit_event.event, "run_exited")
        self.assertEqual(exit_event.result, "control_returned_to_caller")


# ── 验收矩阵 5：缺陷版必须能被测试发现 ─────────────────────────────────


class TestDefectIsDetectable(ProtocolCase):
    def test_waiting_marker_without_stop_is_detected(self):
        result, _store, _client = self.run_naive_scripted(
            [BRIEF, WAIT, WAIT], max_steps=4, mark_waiting=True
        )
        state = result.final_state
        # 数据标记为真……
        self.assertTrue(state.waiting_marker)
        # ……但状态不是等待，循环也还在转：同一条等待信号被忽略了两次。
        # 证据用事件条数，不用模型调用数——脚本控制器本身不调用模型。
        self.assertIsNot(state.status, RunStatus.WAITING_FOR_USER)
        ignored = [e for e in result.trace if e.event == "wait_ignored"]
        self.assertEqual(len(ignored), 2, "循环没有停下：等待信号被反复忽略")
        # 判据能抓住它：这就是「测试可以发现缺陷」。
        with self.assertRaises(AssertionError):
            self.assert_run_suspended(result)


# ── 验收矩阵 6：Gateway 拦截不等于 Run 暂停 ───────────────────────────


class TestGatewayVersusRuntime(ProtocolCase):
    def test_gateway_rejection_is_not_suspension(self):
        result, store, _client = self.run_naive_scripted([BRIEF, WRITE], max_steps=2)
        state = result.final_state
        self.assertEqual(store.draft_count(), 0, "未获批的写入不得落库")
        self.assertFalse(state.draft_written)
        self.assertGreaterEqual(state.rejected_actions, 1)
        self.assertIn(
            "blocked_by_action_gateway", [event.result for event in result.trace]
        )
        # 被拦住 ≠ 停下：Run 既没有进入等待态，也没有 pending request。
        self.assertIsNot(state.status, RunStatus.WAITING_FOR_USER)
        self.assertIsNone(state.pending)
        self.assertFalse(is_run_suspended(result))


# ── 验收矩阵 7：非法状态下的等待信号被拒绝 ────────────────────────────


class TestPreconditions(ProtocolCase):
    def test_wait_signal_without_object_is_rejected(self):
        result, _store, _client = self.run_scripted([WAIT])
        state = result.final_state
        self.assertEqual(state.rejected_signals, 1)
        self.assertIs(state.status, RunStatus.FAILED)
        self.assertEqual(result.terminal_reason, "wait_signal_without_pending_object")
        self.assertIsNone(state.pending, "被拒绝的等待不得留下 pending request")

    def test_wait_signal_without_question_is_rejected(self):
        result, _store, _client = self.run_scripted(
            [BRIEF, {"type": "REQUEST_USER_INPUT"}]
        )
        self.assertEqual(result.final_state.rejected_signals, 1)
        self.assertIs(result.final_state.status, RunStatus.FAILED)
        self.assertEqual(result.terminal_reason, "wait_signal_without_question")

    def test_premature_finish_is_rejected(self):
        # max_steps=1：只让模型提出一次「完成」，观察它被拒绝而不是被接受。
        result, _store, _client = self.run_scripted([{"type": "FINISH"}], max_steps=1)
        state = result.final_state
        self.assertFalse(state.brief_created)
        self.assertEqual(state.rejected_actions, 1)
        self.assertIs(state.status, RunStatus.RUNNING)
        self.assertEqual(result.terminal_reason, "budget_exhausted")

    def test_unknown_action_never_becomes_success(self):
        result, store, _client = self.run_scripted(
            [{"type": "EXECUTE_TOOL", "action": "delete_everything", "args": {}}],
            max_steps=3,
        )
        state = result.final_state
        self.assertEqual(state.tool_attempts, 0, "未知动作不该走到工具层")
        self.assertGreaterEqual(state.rejected_actions, 1)
        self.assertFalse(state.brief_created)
        self.assertFalse(state.draft_written)
        self.assertEqual(store.draft_count(), 0)

    def test_unparseable_output_fails_explicitly(self):
        result, _store, _client = self.run_scripted([{"type": "MAYBE_LATER"}])
        self.assertEqual(result.terminal_reason, "parse_failed")
        self.assertIs(result.final_state.status, RunStatus.FAILED)
        self.assertEqual(result.final_state.rejected_signals, 1)


# ── 验收矩阵 9、10：三条来源共用一个 Runtime、Trace 顺序一致 ──────────


class TestThreeSources(ProtocolCase):
    def _run_all_sources(self) -> List[ModeResult]:
        results = []
        for factory in (ReactController, PlannerController, WorkflowController):
            client = FixtureLlmClient()
            results.append(
                run_with_runtime(factory(client), client, ActionGateway(VirtualStore()))
            )
        return results

    def test_three_sources_share_one_runtime_entry(self):
        for result in self._run_all_sources():
            self.assert_run_suspended(result)
            self.assertEqual(
                wait_event_sequence(result.trace),
                list(RUNTIME_EVENT_ORDER),
                f"{result.mode} 的等待事件序列与其他来源不一致",
            )

    def test_only_runtime_performs_state_migration(self):
        for result in self._run_all_sources():
            transitions = [e for e in result.trace if e.event == "state_transition"]
            self.assertTrue(transitions, f"{result.mode} 没有状态迁移事件")
            for event in transitions:
                self.assertEqual(event.decision_maker, "runtime")
            suspend_events = [
                e
                for e in result.trace
                if e.event == "state_transition" and e.runtime_decision == "SUSPEND_RUN"
            ]
            self.assertEqual(len(suspend_events), 1, "迁移点应当唯一")

    def test_trace_record_carries_contract_fields(self):
        result, _store, _client = self.run_scripted([BRIEF, WAIT])
        record = [e for e in result.trace if e.event == "run_exited"][0]
        self.assertEqual(record.signal_source, "script")
        self.assertEqual(record.signal_type, DecisionType.REQUEST_USER_INPUT.value)
        self.assertEqual(record.runtime_decision, "SUSPEND_RUN")
        self.assertEqual(record.state_before, RunStatus.WAITING_FOR_USER.value)
        self.assertEqual(record.state_after, RunStatus.WAITING_FOR_USER.value)
        self.assertEqual(record.pending_request_id, "approval_001")
        self.assertEqual(record.model_calls_after_wait, 0)
        self.assertEqual(record.tool_calls_after_wait, 0)


# ── 本次重构修正的两处问题 ─────────────────────────────────────────────


class TestFairnessAndBranch(ProtocolCase):
    def test_prompts_share_one_material_list_without_hardcoded_order(self):
        prompts: List[tuple] = []
        for factory in (ReactController, PlannerController):
            client = FixtureLlmClient()
            run_with_runtime(factory(client), client, ActionGateway(VirtualStore()))
            prompts.extend(client.prompts)

        material_hint = "可用资料：" + "、".join(VISIBLE_MATERIALS)
        for _purpose, system, _user in prompts:
            self.assertNotIn("先读 material_1", system, "提示词不得硬编码读取顺序")
            self.assertNotIn("再读 material_2", system, "提示词不得硬编码读取顺序")
            self.assertIn(material_hint, system, "两个控制器应拿到同一份资料清单")

    def test_workflow_branch_is_conditional(self):
        # 有 follow_up 线索：真的走进分支读第二份资料。
        client = FixtureLlmClient()
        controller = WorkflowController(client)
        result = run_with_runtime(controller, client, ActionGateway(VirtualStore()))
        self.assertTrue(controller.branch_taken)
        self.assertIn("material_2", controller.read_ids)
        self.assert_run_suspended(result)

        # 没有线索：不读第二份资料，分支为假——这才是真条件分支。
        client = FixtureLlmClient()
        controller = WorkflowController(client)
        result = run_with_runtime(
            controller, client, ActionGateway(VirtualStore(), follow_up_enabled=False)
        )
        self.assertFalse(controller.branch_taken)
        self.assertNotIn("material_2", controller.read_ids)
        self.assertEqual(controller.read_ids, ["material_1"])
        self.assert_run_suspended(result)

    def test_plan_validation_is_structural_only(self):
        # 结构合法：等待点在受保护写入之前。
        self.assertEqual(validate_plan([BRIEF, WAIT, WRITE])[0], "ACCEPT")
        # 结构缺口：受保护写入之前没有等待点。
        self.assertEqual(validate_plan([BRIEF, WRITE])[0], "REVISE")
        # 结构非法：未知决定类型。
        self.assertEqual(validate_plan([{"type": "MAYBE"}])[0], "REJECT")

        # 校验通过 ≠ 已经获批：跑完 Planner 夹具后，approval_granted 仍为假。
        client = FixtureLlmClient()
        controller = PlannerController(client)
        result = run_with_runtime(controller, client, ActionGateway(VirtualStore()))
        self.assertEqual(result.plan_status, "ACCEPT")
        self.assertFalse(result.final_state.approval_granted)
        self.assertFalse(result.final_state.draft_written)
        self.assert_run_suspended(result)


if __name__ == "__main__":
    unittest.main()
