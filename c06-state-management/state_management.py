#!/usr/bin/env python3
"""C06 成文 demo：把 C05 只在内存里的循环，升级成「断了能接回来、有副作用的步骤不重复」的版本。

核心结论（这一篇真正要回答的问题）：

    「业务已经成功了，但 Agent 还没来得及把它记下来，怎么办？」

围绕这个问题，本 demo 在 C05 的 ReAct 循环之上，做了三件 C05 没有的事：

1. 状态显式化 + 可落盘（next_step / done_steps / checkpoint）。
   进度不再只活在内存的 messages 里，而是被单独拎出来、能存盘、能恢复。
   next_step 记录「循环此刻处于哪个运行阶段」（等模型决策 / 等工具结果），
   具体下一步做什么业务动作，仍由模型决定（ReAct 路线不变）。

2. 业务数据真正落盘（SQLite）。
   库存、幂等记录都存在 SQLite 文件里，进程重启后还在。这才能构造「扣库存成功、
   但 checkpoint 还没写」的失败窗口，并验证恢复时不会重复扣。

3. 副作用幂等靠「事务 + 唯一约束」落地。
   deduct 里「查幂等 -> 扣库存 -> 写幂等」三步放在同一个事务里，幂等键带唯一约束。
   并发 / 重放时，唯一约束冲突即返回 ALREADY_DONE，业务效果不会重复。

真实 LLM 只负责「下一步做什么」的决策，但为了离线确定性，demo 用一个顺序脚本模型
替代真实 LLM；库存、通知、checkpoint、幂等全部真实落盘，不依赖外部 API。
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    MAX_STEPS = "MAX_STEPS"


# 运行阶段：循环此刻在等什么。这是「运行状态」而非「业务进度」——具体下一步
# 做哪个业务动作，仍由模型决定（ReAct 路线）。
class NextStep(str, Enum):
    WAITING_MODEL = "waiting_model"  # 等模型给出下一轮决策
    WAITING_TOOL = "waiting_tool"    # 等工具结果回填（模型已发起一次工具调用）


# 有副作用（执行后不可靠地可撤销）的步骤，恢复时要靠幂等兜底，而不是靠 checkpoint。
SIDE_EFFECT_STEPS = {"deduct_inventory", "notify_shipped"}


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str = "local-call"


@dataclass
class ModelTurn:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class Model(Protocol):
    def decide(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn: ...


# ---------------------------------------------------------------------------
# 业务数据：库存 + 幂等记录，落 SQLite。
# ---------------------------------------------------------------------------

class Inventory:
    """带副作用的业务夹具，数据持久化在 SQLite 文件里。

    幂等靠「唯一约束 + 事务」：deduct 里「查幂等 -> 扣库存 -> 写幂等」在同一事务，
    幂等键 (order_id, sku) 建 UNIQUE 约束。并发或重放时，第二次插入会触发
    IntegrityError，即返回 ALREADY_DONE，不会重复扣。

    这模拟的是生产里「数据库扣款记录」这类外部世界的痕迹：进程重启了它还在，
    是「不重复执行」的最终兜底。
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS stock (
                sku TEXT PRIMARY KEY,
                qty INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS side_effect_log (
                step TEXT NOT NULL,       -- deduct / notify
                order_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                PRIMARY KEY (step, order_id, sku)
            );
            """
        )
        # 幂等键：同一订单同一 SKU 的扣库存只允许一次。PRIMARY KEY 即唯一约束。
        self.conn.executescript(
            """
            INSERT OR IGNORE INTO stock(sku, qty) VALUES ('A-100', 10);
            INSERT OR IGNORE INTO stock(sku, qty) VALUES ('B-200', 5);
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def check(self, sku: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT qty FROM stock WHERE sku = ?", (sku,)).fetchone()
        return {"status": "SUCCESS", "sku": sku, "available": row[0] if row else 0}

    def deduct(self, sku: str, order_id: str) -> dict[str, Any]:
        """扣库存：查幂等 -> 扣库存 -> 写幂等，三步同一事务，唯一约束兜底。"""
        try:
            with self.conn:  # 一个事务；任一步失败整体回滚
                # 1) 查幂等：这笔订单这个 SKU 扣过没有
                done = self.conn.execute(
                    "SELECT 1 FROM side_effect_log WHERE step='deduct' AND order_id=? AND sku=?",
                    (order_id, sku),
                ).fetchone()
                if done:
                    return {"status": "ALREADY_DONE", "sku": sku, "order_id": order_id}
                # 2) 扣库存
                row = self.conn.execute("SELECT qty FROM stock WHERE sku = ?", (sku,)).fetchone()
                if row is None or row[0] <= 0:
                    return {"status": "OUT_OF_STOCK", "sku": sku}
                self.conn.execute("UPDATE stock SET qty = qty - 1 WHERE sku = ?", (sku,))
                # 3) 写幂等（唯一约束：并发/重放时这里会抛 IntegrityError -> 外层转 ALREADY_DONE）
                self.conn.execute(
                    "INSERT INTO side_effect_log(step, order_id, sku) VALUES ('deduct', ?, ?)",
                    (order_id, sku),
                )
            return {"status": "DEDUCTED", "sku": sku}
        except sqlite3.IntegrityError:
            return {"status": "ALREADY_DONE", "sku": sku, "order_id": order_id}

    def notify(self, order_id: str) -> dict[str, Any]:
        try:
            with self.conn:
                done = self.conn.execute(
                    "SELECT 1 FROM side_effect_log WHERE step='notify' AND order_id=?",
                    (order_id,),
                ).fetchone()
                if done:
                    return {"status": "ALREADY_DONE", "order_id": order_id}
                self.conn.execute(
                    "INSERT INTO side_effect_log(step, order_id, sku) VALUES ('notify', ?, '')",
                    (order_id,),
                )
            return {"status": "NOTIFIED", "order_id": order_id}
        except sqlite3.IntegrityError:
            return {"status": "ALREADY_DONE", "order_id": order_id}

    def side_effects(self) -> list[tuple[str, str, str]]:
        return self.conn.execute(
            "SELECT step, order_id, sku FROM side_effect_log ORDER BY rowid"
        ).fetchall()

    def stock_qty(self, sku: str) -> int:
        row = self.conn.execute("SELECT qty FROM stock WHERE sku = ?", (sku,)).fetchone()
        return row[0] if row else 0


class ToolRegistry:
    REQUIRED = {
        "check_inventory": ("sku",),
        "deduct_inventory": ("sku", "order_id"),
        "notify_shipped": ("order_id",),
    }

    def __init__(self, inventory: Inventory) -> None:
        self.inventory = inventory

    def schemas(self) -> list[dict[str, Any]]:
        return [
            self._schema("check_inventory", "查询 SKU 库存，返回可售数量", "sku"),
            self._schema("deduct_inventory", "扣减 SKU 库存（有副作用，需幂等）", "sku", "order_id"),
            self._schema("notify_shipped", "通知用户已发货（有副作用，需幂等）", "order_id"),
        ]

    @staticmethod
    def _schema(name: str, description: str, *required: str) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {key: {"type": "string"} for key in required},
                    "required": list(required),
                },
            },
        }

    def execute(self, call: ToolCall) -> dict[str, Any]:
        required = self.REQUIRED.get(call.name)
        if required is None:
            return {"status": "ERROR", "code": "UNKNOWN_TOOL"}
        invalid = [
            key
            for key in required
            if not isinstance(call.arguments.get(key), str) or not call.arguments[key].strip()
        ]
        if invalid:
            return {"status": "ERROR", "code": "INVALID_ARGUMENT", "missing_or_invalid": invalid}
        return getattr(self, call.name)(**call.arguments)

    def check_inventory(self, sku: str) -> dict[str, Any]:
        return self.inventory.check(sku)

    def deduct_inventory(self, sku: str, order_id: str) -> dict[str, Any]:
        return self.inventory.deduct(sku, order_id)

    def notify_shipped(self, order_id: str) -> dict[str, Any]:
        return self.inventory.notify(order_id)


# ---------------------------------------------------------------------------
# 显式状态 + checkpoint（原子写）。
# ---------------------------------------------------------------------------

@dataclass
class AgentState:
    """显式状态：把 C05 隐式塞进 messages 的信息拆成清晰字段，并支持落盘。

    next_step 是「运行阶段」：循环此刻在等模型决策（waiting_model）还是在等
    工具结果（waiting_tool）。它描述的是运行时进度，而不是「该调哪个业务工具」——
    具体下一步做什么，仍由模型决定（ReAct 路线不变）。
    """

    task: dict[str, Any]
    messages: list[dict[str, Any]] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    status: RunStatus = RunStatus.RUNNING
    next_step: str = NextStep.WAITING_MODEL.value  # 运行阶段：等模型 / 等工具
    done_steps: list[str] = field(default_factory=list)  # 已完成副作用步骤（审计 / 幂等依据）


class CheckpointStore:
    """把 AgentState 原子落盘：写临时文件再 rename，避免写到一半被中断留下半截文件。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, state: AgentState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(self._to_dict(state), ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)  # 原子替换：旧文件要么完整要么保留
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def load(self) -> AgentState | None:
        if not self.path.exists():
            return None
        return self._from_dict(json.loads(self.path.read_text(encoding="utf-8")))

    @staticmethod
    def _to_dict(state: AgentState) -> dict[str, Any]:
        return {
            "task": state.task,
            "messages": state.messages,
            "trace": state.trace,
            "status": state.status.value,
            "next_step": state.next_step,
            "done_steps": state.done_steps,
        }

    @staticmethod
    def _from_dict(data: dict[str, Any]) -> AgentState:
        return AgentState(
            task=data["task"],
            messages=data["messages"],
            trace=data["trace"],
            status=RunStatus(data["status"]),
            next_step=data["next_step"],
            done_steps=data["done_steps"],
        )


# ---------------------------------------------------------------------------
# 运行时：ReAct 循环 + checkpoint + 副作用幂等。
# ---------------------------------------------------------------------------

class DurableRuntime:
    """在 C05 ReAct 循环的基础上，加入 checkpoint + 崩溃恢复 + 副作用幂等。

    关键点（也是这一篇与 C05 的根本区别）：
    - 循环结构不变：模型 decide -> 执行工具 -> 观察回填 -> 再 decide（ReAct）。
    - 每一步模型决策前，把「运行阶段」记为 waiting_model，有副作用步骤执行完
      记为 waiting_tool 并立即 checkpoint。
    - 有副作用的步骤，其「到底做没做」由 SQLite 里的幂等记录说了算，
      checkpoint 只是「我记到哪了」，二者各司其职。
    """

    def __init__(
        self,
        model: Model,
        registry: ToolRegistry,
        checkpoint: CheckpointStore | None = None,
    ) -> None:
        self.model = model
        self.registry = registry
        self.checkpoint = checkpoint

    def start(self, task: dict[str, Any], max_steps: int = 8) -> AgentState:
        state = AgentState(
            task=task,
            messages=[{"role": "user", "content": self._task_prompt(task)}],
        )
        return self._drive(state, max_steps)

    def recover(self, max_steps: int = 8) -> AgentState:
        """崩溃后从最近 checkpoint 恢复，接着跑（决策上下文仍在 messages 里）。"""
        if self.checkpoint is None:
            raise ValueError("recover requires a checkpoint store")
        state = self.checkpoint.load()
        if state is None:
            raise ValueError("no checkpoint to recover from")
        state.trace.append("recovered_from_checkpoint")
        return self._drive(state, max_steps)

    def _drive(self, state: AgentState, max_steps: int) -> AgentState:
        for _ in range(max_steps):
            # 等模型决策：下一步做什么业务动作，由模型根据 messages 决定。
            state.next_step = NextStep.WAITING_MODEL.value
            turn = self.model.decide(state.messages, self.registry.schemas())
            if turn is None:
                # 模型不再响应（脚本耗尽 / 进程被杀）：保留 RUNNING，不做 final 收尾。
                state.trace.append("crashed_here")
                return state

            if not turn.tool_calls:
                # 模型不再发起工具调用，而是给出最终答复 -> 完成。
                state.messages.append({"role": "assistant", "content": turn.content or ""})
                state.status = RunStatus.COMPLETED
                state.trace.append("model_final")
                self._checkpoint(state)
                return state

            # 模型发起工具调用：进入「等工具结果」阶段。
            call = turn.tool_calls[0]
            state.next_step = NextStep.WAITING_TOOL.value

            # 记录完整的工具调用消息链：先 assistant 的 tool_call，再 tool 结果。
            state.messages.append(
                {
                    "role": "assistant",
                    "content": turn.content,
                    "tool_calls": [
                        {
                            "id": call.call_id,
                            "type": "function",
                            "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)},
                        }
                    ],
                }
            )
            observation = self.registry.execute(call)
            state.trace.append(f"step tool={call.name} args={json.dumps(call.arguments, ensure_ascii=False)}")
            state.trace.append(f"observation={observation['status']}")
            state.messages.append(
                {"role": "tool", "tool_call_id": call.call_id, "content": json.dumps(observation, ensure_ascii=False)}
            )

            # 有副作用的步骤：记入 done_steps，并立即 checkpoint——
            # 「我已经做过了」这个事实要尽快持久化。
            if call.name in SIDE_EFFECT_STEPS and observation["status"] in {"DEDUCTED", "NOTIFIED"}:
                state.done_steps.append(f"{call.name}:{json.dumps(call.arguments, ensure_ascii=False)}")
                self._checkpoint(state)
                state.trace.append("checkpoint_saved")

        state.status = RunStatus.MAX_STEPS
        return state

    def _checkpoint(self, state: AgentState) -> None:
        if self.checkpoint is not None:
            self.checkpoint.save(state)

    @staticmethod
    def _task_prompt(task: dict[str, Any]) -> str:
        return f"处理订单 {task['order_id']}：先查库存，再扣库存，最后发发货通知。SKU 是 {task['sku']}。"


class ScriptedModel:
    """离线夹具：按脚本顺序吐出工具调用，替代真实 LLM 的逐步决策。

    脚本耗尽时返回 None，模拟「进程被杀、模型不再响应」——这比伪造一句 final
    更接近真实的崩溃。恢复后，新的 ScriptedModel 接着走「发通知」这步。
    """

    def __init__(self, script: list[ModelTurn]) -> None:
        self.script = list(script)
        self.cursor = 0

    def decide(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn | None:
        if self.cursor < len(self.script):
            turn = self.script[self.cursor]
            self.cursor += 1
            return turn
        return None  # 脚本耗尽 = 进程崩溃，模型不再产生任何 turn


def scripted_plan(task: dict[str, Any]) -> list[ModelTurn]:
    """一份 ReAct 决策脚本：模型依次决定调 check -> deduct -> notify，最后给最终答复。"""
    sku, order_id = task["sku"], task["order_id"]
    return [
        ModelTurn(tool_calls=[ToolCall("check_inventory", {"sku": sku})]),
        ModelTurn(tool_calls=[ToolCall("deduct_inventory", {"sku": sku, "order_id": order_id})]),
        ModelTurn(tool_calls=[ToolCall("notify_shipped", {"order_id": order_id})]),
        ModelTurn(content="订单处理完成"),
    ]


def print_state(state: AgentState) -> None:
    print("\n".join(state.trace))
    print(f"status={state.status.value} next_step={state.next_step} done_steps={state.done_steps}")


def _summarize(conn_or_inv: Inventory) -> str:
    return ", ".join(f"{s}:{o}:{k}" for s, o, k in conn_or_inv.side_effects())


def main() -> None:
    """演示两条路径：
    1. 正常跑完：模型逐步决策 查库存 -> 扣库存 -> 发通知 -> 完成。
    2. 崩溃恢复：扣库存成功后、发通知前崩溃，再恢复，验证不重复扣。
    """
    task = {"order_id": "O-1001", "sku": "A-100"}

    # 清理上一次运行残留的 demo 文件，保证每次演示从干净状态开始。
    for p in (
        "/tmp/c06-demo-inventory-1.sqlite",
        "/tmp/c06-demo-inventory.sqlite",
        "/tmp/c06-demo-checkpoint.json",
    ):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass

    print("===== 路径 1：正常跑完 =====")
    inv1 = Inventory("/tmp/c06-demo-inventory-1.sqlite")
    rt1 = DurableRuntime(ScriptedModel(scripted_plan(task)), ToolRegistry(inv1))
    s1 = rt1.start(task)
    print_state(s1)
    print(f"stock[A-100]={inv1.stock_qty('A-100')} side_effects={_summarize(inv1)}")
    inv1.close()

    # 路径 2：真实两进程崩溃恢复。
    # 进程 A：模型决策到「扣库存」后脚本耗尽（模型不再响应，模拟崩溃），
    # 此时扣库存的副作用已发生、checkpoint 已写（扣库存执行完立即落盘）。
    print("\n===== 路径 2：崩溃恢复（发通知前崩溃）=====")
    db_path = "/tmp/c06-demo-inventory.sqlite"
    ckpt = CheckpointStore("/tmp/c06-demo-checkpoint.json")

    # 子进程：跑「查库存 + 扣库存」两轮决策，然后脚本耗尽，进程退出。
    here = os.path.dirname(os.path.abspath(__file__))
    code = (
        f"import sys; sys.path.insert(0, {here!r})\n"
        "from state_management import Inventory, DurableRuntime, ScriptedModel, ToolRegistry, CheckpointStore, scripted_plan\n"
        "task={'order_id':'O-1001','sku':'A-100'}\n"
        f"inv=Inventory({db_path!r})\n"
        f"rt=DurableRuntime(ScriptedModel(scripted_plan(task)[:2]), ToolRegistry(inv), checkpoint=CheckpointStore({str(ckpt.path)!r}))\n"
        "st=rt.start(task)  # 跑完 check + deduct 后脚本耗尽，模拟崩溃（进程退出）\n"
        "print('CRASH', st.status.value, st.next_step, st.done_steps)\n"
        "inv.close()\n"
    )

    import subprocess
    subprocess.run([sys.executable, "-c", code], check=True)

    # 进程 B：全新进程恢复，新的 ScriptedModel 接着走「发通知 -> 完成」。
    print("--- (进程崩溃，全新进程恢复) ---")
    recover_script = [
        ModelTurn(tool_calls=[ToolCall("notify_shipped", {"order_id": task["order_id"]})]),
        ModelTurn(content="订单处理完成"),
    ]
    inv2 = Inventory(db_path)
    rt2 = DurableRuntime(ScriptedModel(recover_script), ToolRegistry(inv2), checkpoint=ckpt)
    s2 = rt2.recover()
    print_state(s2)
    print(f"stock[A-100]={inv2.stock_qty('A-100')} side_effects={_summarize(inv2)}")
    deduct_count = sum(1 for s, _, _ in inv2.side_effects() if s == "deduct")
    notify_count = sum(1 for s, _, _ in inv2.side_effects() if s == "notify")
    print(f"deduct_count={deduct_count} notify_count={notify_count}")
    assert deduct_count == 1, "扣库存应只执行一次（幂等）"
    assert notify_count == 1, "恢复后应补上发通知"
    inv2.close()


if __name__ == "__main__":
    main()
