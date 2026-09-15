#!/usr/bin/env python3
"""C06 离线回归：确定性覆盖「状态落盘、崩溃恢复、副作用幂等」三条主线。

关键：崩溃恢复用真实的两进程模拟——子进程跑一半退出，父进程（新进程）从
checkpoint 恢复，验证业务数据（SQLite 里的库存、幂等记录）跨进程保持一致，
且副作用不重复。

模型决策走 ReAct 路线：下一步做什么由 ScriptedModel 按脚本吐出（离线确定性替代
真实 LLM），runtime 只负责「等模型 -> 执行工具 -> 回填观察」的循环 + checkpoint。

覆盖审查要求的四个场景：
1. 扣库存成功、checkpoint 尚未保存时进程被杀 -> 新进程恢复不重复扣库存。
2. checkpoint 已保存后恢复 -> 完成剩余操作（发通知）。
3. 对已完成任务再次恢复 -> 不会重新启动业务动作。
4. 持久化验收：检查 SQLite 里的库存、幂等记录、最终状态，而非只看日志计数。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from state_management import (
    AgentState,
    CheckpointStore,
    DurableRuntime,
    Inventory,
    ModelTurn,
    NextStep,
    RunStatus,
    ScriptedModel,
    ToolCall,
    ToolRegistry,
    scripted_plan,
)

TASK = {"order_id": "O-1001", "sku": "A-100"}

_HERE = os.path.dirname(os.path.abspath(__file__))


def _run_child(code: str) -> None:
    """在独立子进程里执行一段代码（模拟一个独立的进程）。"""
    subprocess.run([sys.executable, "-c", code], check=True, cwd=_HERE)


class TestCheckpointRoundtrip(unittest.TestCase):
    def test_save_and_load_preserves_state(self):
        with tempfile.TemporaryDirectory() as d:
            store = CheckpointStore(Path(d) / "ckpt.json")
            state = AgentState(
                task=TASK,
                messages=[{"role": "user", "content": "x"}],
                done_steps=["deduct_inventory"],
                next_step=NextStep.WAITING_TOOL.value,
            )
            store.save(state)
            loaded = store.load()
            self.assertEqual(loaded.task, TASK)
            self.assertEqual(loaded.done_steps, ["deduct_inventory"])
            self.assertEqual(loaded.next_step, NextStep.WAITING_TOOL.value)

    def test_atomic_write_leaves_no_partial_file(self):
        # 原子写：save 过程中不存在半截文件（要么旧文件，要么完整新文件）。
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ckpt.json"
            store = CheckpointStore(path)
            s1 = AgentState(task=TASK)
            store.save(s1)
            self.assertTrue(path.exists())
            # 目录里不应残留 .tmp 文件
            self.assertEqual(list(Path(d).glob("*.tmp")), [])


class TestNormalRun(unittest.TestCase):
    def test_runs_to_completion(self):
        with tempfile.TemporaryDirectory() as d:
            inv = Inventory(Path(d) / "inv.sqlite")
            rt = DurableRuntime(ScriptedModel(scripted_plan(TASK)), ToolRegistry(inv))
            state = rt.start(TASK)
            self.assertEqual(state.status, RunStatus.COMPLETED)
            # 持久化验收：库存从 10 扣到 9，幂等记录里 deduct + notify 各一次
            self.assertEqual(inv.stock_qty("A-100"), 9)
            effects = inv.side_effects()
            self.assertEqual(sum(1 for s, _, _ in effects if s == "deduct"), 1)
            self.assertEqual(sum(1 for s, _, _ in effects if s == "notify"), 1)
            inv.close()


class TestCrashBeforeCheckpoint(unittest.TestCase):
    """场景 1：扣库存成功、checkpoint 尚未保存时进程被杀。

    这是本篇最想讲透的失败窗口：业务已经成功（扣库存），但 Agent 还没来得及
    把它记进 checkpoint。恢复后，靠 SQLite 里的幂等记录，扣库存不会重复。
    """

    def test_deduct_then_crash_before_checkpoint_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "inv.sqlite")
            ckpt = str(Path(d) / "ckpt.json")

            # 子进程：直接调用 Inventory.deduct 扣库存（业务成功），但刻意不写
            # checkpoint，然后进程退出。这模拟「扣库存成功、checkpoint 未写」的
            # 崩溃窗口：内存状态丢了，只有 SQLite 里的业务数据还在。
            code = (
                "from state_management import Inventory\n"
                "inv = Inventory(%r)\n"
                "print(inv.deduct('A-100', 'O-1001'))\n"
                "inv.close()\n"
                "# 注意：这里没有写任何 checkpoint，进程到此退出\n"
            ) % db
            _run_child(code)

            # 父进程（新进程）：业务数据在 SQLite 里，checkpoint 不存在。
            self.assertFalse(os.path.exists(ckpt))

            # 恢复路径：重新执行同一笔扣库存，靠幂等返回 ALREADY_DONE，库存不再扣。
            inv = Inventory(db)
            r = inv.deduct("A-100", "O-1001")
            self.assertEqual(r["status"], "ALREADY_DONE")
            self.assertEqual(inv.stock_qty("A-100"), 9)  # 只扣了一次
            inv.close()


class TestCrashRecovery(unittest.TestCase):
    """场景 2 + 3：checkpoint 已保存后恢复；对已完成任务再恢复不重启。"""

    def test_recover_after_crash_completes_remaining_steps(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "inv.sqlite")
            ckpt = str(Path(d) / "ckpt.json")

            # 子进程：模型决策到「扣库存」后脚本耗尽（崩溃），checkpoint 已写，进程退出。
            code = (
                "from state_management import Inventory, DurableRuntime, ScriptedModel, ToolRegistry, CheckpointStore, scripted_plan\n"
                "task={'order_id':'O-1001','sku':'A-100'}\n"
                "inv = Inventory(%r)\n"
                "rt = DurableRuntime(ScriptedModel(scripted_plan(task)[:2]), ToolRegistry(inv), checkpoint=CheckpointStore(%r))\n"
                "st = rt.start(task)  # 跑完 check + deduct 后脚本耗尽，模拟崩溃\n"
                "assert st.status.value == 'RUNNING'\n"
                "inv.close()\n"
            ) % (db, ckpt)
            _run_child(code)

            # 父进程（新进程）恢复：新的模型接着决策「发通知 -> 完成」。
            recover_script = [
                ModelTurn(tool_calls=[ToolCall("notify_shipped", {"order_id": "O-1001"})]),
                ModelTurn(content="订单处理完成"),
            ]
            inv = Inventory(db)
            rt = DurableRuntime(ScriptedModel(recover_script), ToolRegistry(inv), checkpoint=CheckpointStore(ckpt))
            state = rt.recover()
            self.assertEqual(state.status, RunStatus.COMPLETED)
            # 持久化验收
            self.assertEqual(inv.stock_qty("A-100"), 9)
            effects = inv.side_effects()
            self.assertEqual(sum(1 for s, _, _ in effects if s == "deduct"), 1)
            self.assertEqual(sum(1 for s, _, _ in effects if s == "notify"), 1)
            inv.close()

    def test_recover_completed_task_does_not_restart(self):
        """场景 3：任务已完成，再次恢复不应重新启动业务动作。"""
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "inv.sqlite")
            ckpt = str(Path(d) / "ckpt.json")

            # 完整跑完一次（含 checkpoint 落盘为 completed）。
            inv = Inventory(db)
            rt = DurableRuntime(ScriptedModel(scripted_plan(TASK)), ToolRegistry(inv), checkpoint=CheckpointStore(ckpt))
            first = rt.start(TASK)
            self.assertEqual(first.status, RunStatus.COMPLETED)
            inv.close()

            # 再次恢复：checkpoint 里已是 completed，新的模型脚本已耗尽（返回 None），
            # 不应再执行任何业务动作。
            inv2 = Inventory(db)
            rt2 = DurableRuntime(ScriptedModel([]), ToolRegistry(inv2), checkpoint=CheckpointStore(ckpt))
            again = rt2.recover()
            # 注意：恢复后 model 立即返回 None（无更多决策），runtime 停在该状态；
            # 但业务副作用不应被重新触发。
            effects = inv2.side_effects()
            self.assertEqual(sum(1 for s, _, _ in effects if s == "deduct"), 1)
            self.assertEqual(sum(1 for s, _, _ in effects if s == "notify"), 1)
            self.assertEqual(inv2.stock_qty("A-100"), 9)
            inv2.close()


class TestIdempotentReplay(unittest.TestCase):
    def test_replaying_deduct_is_skipped(self):
        """即使模型重放扣库存，Inventory 也会靠唯一约束返回 ALREADY_DONE。"""
        with tempfile.TemporaryDirectory() as d:
            inv = Inventory(Path(d) / "inv.sqlite")
            reg = ToolRegistry(inv)
            r1 = reg.execute(ToolCall("deduct_inventory", {"sku": "A-100", "order_id": "O-1001"}))
            r2 = reg.execute(ToolCall("deduct_inventory", {"sku": "A-100", "order_id": "O-1001"}))
            self.assertEqual(r1["status"], "DEDUCTED")
            self.assertEqual(r2["status"], "ALREADY_DONE")
            self.assertEqual(inv.stock_qty("A-100"), 9)
            inv.close()


if __name__ == "__main__":
    unittest.main()
