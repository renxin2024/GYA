"""C11 暂停协议：工具定义 + 动作准入（ActionGateway）。

三种控制器共享同一套工具和同一个 ActionGateway，
保证比较不会混入「不同的执行规则」。

职责边界（这是第 7 节的核心）：
- ActionGateway 回答「这个动作能不能执行」——准入检查发生在副作用之前。
- Runtime 回答「当前 Run 要不要继续」——状态迁移由它独占。

一个动作被 Gateway 拦住，只说明这个动作没被执行；
它**不**说明 Run 已经暂停。两者是两条不同的判断。
"""

from __future__ import annotations

from typing import List

from state import MATERIALS, RunState, VirtualStore

# 工具名白名单。写工具只有两个：create_brief（生成纲领）与 write_draft（写正文）。
ALL_TOOLS = ("search_materials", "read_material", "create_brief", "write_draft")


class ActionGateway:
    """动作准入与分派：所有工具调用都必须经过这里。

    类名不提供保证；保证来自具体检查条件 + 所有相关调用确实经过它。
    """

    def __init__(self, store: VirtualStore, follow_up_enabled: bool = True) -> None:
        self.store = store
        # 记录 material_1 是否被读过：首次读取只返回部分内容 + 指向 material_2 的线索。
        self._read_log: set = set()
        # follow_up_enabled=False 时，material_1 一次就读到完整内容、不给线索。
        # 这个开关用来验证 Workflow 的分支是**真的**在读结果之后才决定要不要走，
        # 而不是无条件读 material_2。
        self.follow_up_enabled = follow_up_enabled

    def execute(self, action: str, args: dict, state: RunState) -> str:
        """检查并执行一个动作，返回结构化结果字符串。

        返回约定：
        - 读工具成功 → 返回资料内容（含线索）。
        - create_brief 成功 → 返回 brief_id。
        - write_draft 未获批 → "blocked_by_action_gateway"（不写入）。
        - 未知动作 → "blocked_unknown_action"。
        """
        state.tool_attempts += 1

        if action not in ALL_TOOLS:
            state.rejected_actions += 1
            return "blocked_unknown_action"

        result = self._dispatch(action, args, state)

        # 统一累计：成功 / 拒绝。被拒绝的写入绝不落库。
        if _is_success(result):
            state.tool_successes += 1
        elif result.startswith("blocked") or result.startswith("invalid"):
            state.rejected_actions += 1
        return result

    def _dispatch(self, action: str, args: dict, state: RunState) -> str:
        if action == "search_materials":
            return self._search(args.get("query", ""))
        if action == "read_material":
            return self._read(args.get("material_id", ""))
        if action == "create_brief":
            return self._create_brief(args, state)
        if action == "write_draft":
            return self._write_draft(args, state)
        return "blocked_unknown_action"

    # ── 各工具实现 ────────────────────────────────────────────────────

    def _search(self, query: str) -> str:
        if not query:
            return "invalid_query"
        lines = [f"{mid}: {m['title']} — {m['summary']}" for mid, m in MATERIALS.items()]
        return "\n".join(lines)

    def _read(self, material_id: str) -> str:
        if material_id not in MATERIALS:
            return f"material_not_found: {material_id}"
        m = MATERIALS[material_id]

        first_read = material_id not in self._read_log
        self._read_log.add(material_id)

        # 动态场景：首次读取只返回部分内容 + 指向 material_2 的线索。
        # 这条线索只能从这里（工具结果）拿到，绝不写进模型提示词。
        if material_id == "material_1" and first_read and self.follow_up_enabled:
            return f"[partial] {m['content']}\nfollow_up: {m['follow_up']}"
        return f"[full] {m['content']}"

    def _create_brief(self, args: dict, state: RunState) -> str:
        content = args.get("content", "")
        evidence_ids = args.get("evidence_ids", [])
        if not content or not isinstance(evidence_ids, list):
            return "invalid_brief_arguments"

        # 结构准入：纲领必须引用存在的资料 ID。
        # 引用结构有效 ≠ 资料真的支撑论点（那是内容检查，不是这里的结构检查）。
        for eid in evidence_ids:
            if eid not in MATERIALS:
                return f"invalid_evidence_id: {eid}"

        state.brief_created = True
        state.brief_content = content
        state.brief_evidence_ids = list(evidence_ids)
        self.store.save_brief("brief_1", content, list(evidence_ids))
        return "brief_created: brief_1"

    def _write_draft(self, args: dict, state: RunState) -> str:
        # ★受保护写入：准入检查必须在实际写入之前。未获批直接拒绝，不碰 store。
        if not state.approval_granted:
            return "blocked_by_action_gateway"

        content = args.get("content", "")
        if not content:
            return "invalid_draft_content"

        state.draft_written = True
        self.store.save_draft("draft_1", content)
        return "draft_written"


def _is_success(result: str) -> bool:
    return not (
        result.startswith("blocked")
        or result.startswith("invalid")
        or result.startswith("material_not_found")
    )
