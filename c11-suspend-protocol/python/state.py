"""C11 暂停协议：运行态与隔离产物存储。

本文件只放「一次 Run 的可变状态」和「虚拟产物存储」，不含模型调用、不含调度逻辑。
离线测试可以直接 import 本文件，不需要网络或 API Key。

与旧版的关键差异：
- 旧版用一个布尔 `waiting_for_approval` 表示等待。布尔无法表达「非法状态」，
  也无法区分「状态标记为真」与「调度已经退出」。
- 本版用 RunStatus 枚举表达状态，并留下「等待快照」，
  用来在运行结束后计算「等待之后还有没有新的调用」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from protocol import PendingRequest, RunStatus

# ── 资料（教学合成数据，不是权威事实来源）──────────────────────────────
# material_1 首次读取只返回「部分内容」+ 一条指向 material_2 的线索。
# 这条线索只能通过 read_material 的工具结果拿到，不写进任何提示词——
# 这是「观察如何改变决策」能被测出来的前提。
MATERIALS: Dict[str, Dict[str, str]] = {
    "material_1": {
        "title": "Agent 控制模式（局部摘录）",
        "summary": "讲 ReAct 与 Workflow 在决策粒度上的差异，但关键结论在另一份资料里。",
        "content": (
            "ReAct 在每次观察后重新选择动作；Workflow 预定义主要节点。"
            "两者的决策粒度不同，但如何组合、审批边界放在哪里，"
            "需要结合 material_2 里关于「运行时准入」的部分才能下结论。"
        ),
        "follow_up": "这份摘录不完整。继续读 material_2 才能得到关于审批边界与运行时准入的结论。",
    },
    "material_2": {
        "title": "审批边界与运行时准入（完整）",
        "summary": "写操作在通过运行时检查后才执行；等待是控制结果而非数据标记。",
        "content": (
            "生成纲领后必须等待用户确认，确认前不得写正文。"
            "「请求审批」与「已经获批」是两个独立状态：前者是控制流状态，"
            "后者是外部输入。运行时在写操作前检查获批状态，未获批则拒绝。"
        ),
        "follow_up": "",
    },
}

# 三种控制器共享的同一份初始资料清单。
# 旧版把「先读 material_1，再读 material_2」写进 Planner 提示词，
# 等于让 Planner 直接拿到路径信息，而 ReAct 必须自己从工具结果里发现——
# 那场比较对 ReAct 不公平。本版三个控制器拿到同一份清单：
# 知道有哪些资料，但不知道读取顺序。
VISIBLE_MATERIALS: Tuple[str, ...] = ("material_1", "material_2")


@dataclass
class RunState:
    """一次 Run 的可变状态。每种控制器运行前都新建实例，避免产物泄漏。"""

    # 状态：由 Runtime 写入，控制器和模型都改不了
    status: RunStatus = RunStatus.RUNNING

    # 产物
    brief_created: bool = False
    brief_content: str = ""
    brief_evidence_ids: List[str] = field(default_factory=list)
    draft_written: bool = False

    # 审批：外部输入，与「等待」这个状态严格分开
    approval_granted: bool = False

    # 等待中的请求：Run 进入 WAITING_FOR_USER 时写入
    pending: Optional[PendingRequest] = None

    # 缺陷版用的数据标记：用来证明「标记为真」不等于「已经停下」
    waiting_marker: bool = False

    # 统计
    model_calls: int = 0
    tool_attempts: int = 0
    tool_successes: int = 0
    rejected_actions: int = 0
    rejected_signals: int = 0
    usage: Dict[str, int] = field(default_factory=dict)

    # 等待快照：进入 WAITING_FOR_USER 的瞬间记下计数
    model_calls_at_wait: Optional[int] = None
    tool_attempts_at_wait: Optional[int] = None

    def snapshot_wait(self) -> None:
        """进入等待态时调用。没有快照就无法证明「等待之后没有新调用」。"""
        self.model_calls_at_wait = self.model_calls
        self.tool_attempts_at_wait = self.tool_attempts

    def calls_after_wait(self) -> Tuple[int, int]:
        """返回 (模型调用增量, 工具尝试增量)。未进入等待态时恒为 (0, 0)。"""
        if self.model_calls_at_wait is None or self.tool_attempts_at_wait is None:
            return 0, 0
        return (
            self.model_calls - self.model_calls_at_wait,
            self.tool_attempts - self.tool_attempts_at_wait,
        )


class VirtualStore:
    """隔离的产物存储：只存在内存里，不写公开博客、不提交 Git、不部署。"""

    def __init__(self) -> None:
        self._briefs: Dict[str, dict] = {}
        self._drafts: Dict[str, str] = {}

    def save_brief(self, brief_id: str, content: str, evidence_ids: List[str]) -> None:
        self._briefs[brief_id] = {"content": content, "evidence_ids": evidence_ids}

    def save_draft(self, draft_id: str, content: str) -> None:
        self._drafts[draft_id] = content

    def has_brief(self, brief_id: str) -> bool:
        return brief_id in self._briefs

    def has_draft(self, draft_id: str) -> bool:
        return draft_id in self._drafts

    def brief_count(self) -> int:
        return len(self._briefs)

    def draft_count(self) -> int:
        return len(self._drafts)
