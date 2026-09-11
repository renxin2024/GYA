"""C11 暂停协议：三种控制器 —— 等待信号的三个来源。

三者的共同点：它们**只提出决定**，没有任何一个拥有状态迁移权。
调用方（scheduler.run_with_runtime）会把每条决定交给同一个 Runtime。

差别只有一处：等待信号从哪里产生。

- ReactController：模型在观察后主动提出 REQUEST_USER_INPUT。
- PlannerController：等待是计划里的一步，由执行器按计划提出。
- WorkflowController：等待是代码里的固定节点，到达即提出。

公平性约定（旧版的 Planner 提示词里写着「先读 material_1，再读 material_2」，
等于提前把路径告诉了 Planner，而 ReAct 必须自己从工具结果里发现）：
三个控制器拿到**同一份初始资料清单**，但都不知道读取顺序。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from llm import LlmClient
from plan_validator import validate_plan
from state import VISIBLE_MATERIALS, RunState

TASK = "根据给定主题和本地资料，整理有依据的技术文章创作纲领，然后等待用户确认。未经确认，不生成正文草稿。"

# 三个控制器共用的「可用资料」描述：知道有哪些资料，不知道先读哪一份。
_MATERIAL_HINT = "可用资料：" + "、".join(VISIBLE_MATERIALS) + "。资料读取顺序由工具返回的结果决定，不要预设顺序。"

_DECISION_HINT = (
    "决定类型（只返回其中一种）：\n"
    '- {"type": "EXECUTE_TOOL", "action": "工具名", "args": {...}}\n'
    '- {"type": "REQUEST_USER_INPUT", "question": "要问用户的问题"}\n'
    '- {"type": "FINISH"}\n'
)

_TOOL_HINT = (
    "可用工具：\n"
    '- search_materials: {"query": "关键词"}\n'
    '- read_material: {"material_id": "资料ID"}\n'
    '- create_brief: {"content": "纲领正文", "evidence_ids": ["引用的资料ID"]}\n'
    '- write_draft: {"content": "草稿正文"}（受保护写入，确认前绝不能用）\n'
)


class Controller:
    """控制器统一接口。注意它没有 `set_state` 之类的方法——它改不了状态。"""

    name = "controller"
    signal_source = "controller"

    def propose(self, state: RunState, step: int) -> object:
        raise NotImplementedError

    def on_tool_result(self, result: str) -> None:
        """工具执行完的回执。只有 ReAct / Workflow 会用它。"""


class ReactController(Controller):
    """模型在每次观察后重新提出决定。

    它能看到完整的历史观察（不是只看最新一条）——旧稿曾把「ReAct 只能看到当前观察」
    写成绕圈的原因，那句话与代码不符，本版不沿用这个说法。
    """

    name = "react"
    signal_source = "llm"

    def __init__(self, client: LlmClient) -> None:
        self.client = client
        self.observations: List[str] = []

    def propose(self, state: RunState, step: int) -> object:
        system = (
            "你是 ReAct 风格控制器。每次只提出一个决定，返回 JSON 对象。\n"
            + _MATERIAL_HINT
            + "\n"
            + _DECISION_HINT
            + _TOOL_HINT
            + "规则：先读资料，再生成创作纲领（create_brief）。"
            "纲领生成之后，如果需要用户确认才能继续，就提出 REQUEST_USER_INPUT；"
            "确认之前绝不能用 write_draft。"
        )
        payload = {
            "task": TASK,
            "observations": self.observations,
            "brief_created": state.brief_created,
            "approval_granted": state.approval_granted,
        }
        return self.client.complete_json(
            "react", system, json.dumps(payload, ensure_ascii=False)
        )

    def on_tool_result(self, result: str) -> None:
        self.observations.append(result)


class PlannerController(Controller):
    """等待是计划里的一步。

    计划文本本身没有暂停能力：执行器把「请求用户输入」这一步照原样交给 Runtime，
    真正决定停止的是 Runtime，不是那份计划。
    """

    name = "plan_and_execute"
    signal_source = "planner"

    def __init__(self, client: LlmClient) -> None:
        self.client = client
        self.steps: List[Dict[str, Any]] = []
        self.index = 0
        self.plan_status: Optional[str] = None
        self.plan_violations: List[str] = []
        self._planned = False

    def propose(self, state: RunState, step: int) -> object:
        if not self._planned:
            self._planned = True
            response = self.client.complete_json(
                "plan",
                (
                    "你是 Planner。返回 JSON：{\"steps\": [ ... ]}。\n"
                    + _MATERIAL_HINT
                    + "\n每一步都是一个决定：\n"
                    + _DECISION_HINT
                    + _TOOL_HINT
                    + "规则：create_brief 之后、write_draft 之前必须放一个 "
                    "REQUEST_USER_INPUT 步（等待用户确认，它不是工具）。"
                ),
                json.dumps({"task": TASK}, ensure_ascii=False),
            )
            raw_steps = response.get("steps") or []
            self.steps = [s for s in raw_steps if isinstance(s, dict)]
            self.plan_status, self.plan_violations = validate_plan(self.steps)

        if self.index >= len(self.steps):
            # 计划走完但没有等到结果（例如计划里没有等待步）
            return {"type": "FINISH"}
        step_decision = self.steps[self.index]
        self.index += 1
        return step_decision


class WorkflowController(Controller):
    """等待是代码里的固定节点。

    节点序列由代码决定，节点内部的内容仍由模型生成。
    第 3 个节点是**真实的条件分支**：只有工具结果里真的带回了指向另一份资料的线索，
    才会去读那份资料。旧版在这里无条件读 material_2，却在 Trace 里把它标成
    「读到 follow_up 触发的分支」——那是假的。
    """

    name = "workflow"
    signal_source = "workflow"

    def __init__(self, client: LlmClient) -> None:
        self.client = client
        self.node = 0
        self.last_result = ""
        self.branch_taken: Optional[bool] = None
        self.read_ids: List[str] = []

    def propose(self, state: RunState, step: int) -> object:
        self.node += 1

        if self.node == 1:
            return {
                "type": "EXECUTE_TOOL",
                "action": "search_materials",
                "args": {"query": "控制模式"},
            }

        if self.node == 2:
            target_id = VISIBLE_MATERIALS[0]
            self.read_ids.append(target_id)
            return {
                "type": "EXECUTE_TOOL",
                "action": "read_material",
                "args": {"material_id": target_id},
            }

        if self.node == 3:
            # 真实分支：看上一个节点的实际结果，而不是假设它一定带线索。
            target = self._follow_up_target(self.last_result)
            if target is not None and target not in self.read_ids:
                self.branch_taken = True
                self.read_ids.append(target)
                return {
                    "type": "EXECUTE_TOOL",
                    "action": "read_material",
                    "args": {"material_id": target},
                }
            self.branch_taken = False
            # 没有线索就不读第二份：把节点指针推到读取节点的下一位，
            # 让下一个节点去生成纲领。否则纲领会在节点 3、4 各生成一次。
            self.node = 4
            return self._propose_brief(state)

        if self.node == 4:
            return self._propose_brief(state)

        if self.node == 5:
            return {
                "type": "REQUEST_USER_INPUT",
                "question": "创作纲领已生成，是否继续生成正文草稿？",
            }

        # 正常流程不会走到这里：节点 5 提出等待后，Runtime 会让 Run 挂起。
        return {"type": "FINISH"}

    def on_tool_result(self, result: str) -> None:
        """只记下最近一次工具结果：第 3 个节点要根据它判断要不要走进分支。"""
        self.last_result = result

    # ── 内部 ──────────────────────────────────────────────────────────

    def _propose_brief(self, state: RunState) -> object:
        """节点内容由模型生成，路由仍由代码决定。"""
        response = self.client.complete_json(
            "workflow_content",
            "你只负责生成创作纲领摘要，返回 JSON：{\"brief_summary\": \"...\"}。",
            json.dumps({"task": TASK, "read": self.read_ids}, ensure_ascii=False),
        )
        summary = response.get("brief_summary") or ""
        evidence = self.read_ids or list(VISIBLE_MATERIALS)
        return {
            "type": "EXECUTE_TOOL",
            "action": "create_brief",
            "args": {"content": summary, "evidence_ids": evidence},
        }

    @staticmethod
    def _follow_up_target(result: str) -> Optional[str]:
        """从工具结果里解析「接下来该读哪一份资料」。没有线索就返回 None。"""
        if "follow_up:" not in result:
            return None
        match = re.search(r"(material_\d+)", result.split("follow_up:", 1)[1])
        return match.group(1) if match else None


class ScriptedController(Controller):
    """按脚本提出决定，用于确定性测试与故障注入。

    它不代表任何一种真实控制模式，只用来把某一条决定单独喂给 Runtime 或朴素执行器。
    """

    name = "scripted"
    signal_source = "script"

    def __init__(self, decisions: List[Dict[str, Any]]) -> None:
        self.decisions = list(decisions)
        self.index = 0

    def propose(self, state: RunState, step: int) -> object:
        if self.index >= len(self.decisions):
            return {"type": "FINISH"}
        decision = self.decisions[self.index]
        self.index += 1
        return decision
