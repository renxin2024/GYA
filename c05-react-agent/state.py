#!/usr/bin/env python3
"""C05 state.py：状态管理（对话历史 + 步骤记录 + 终止条件）。

循环里"记住之前发生了什么"靠的是 state——每次 Thought/Action/Observation
都追加进来，下次构造 prompt 时把完整历史喂给模型。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class StepRecord:
    step: int
    thought: str                 # 模型思考（reasoning_content）
    action: str                  # 工具调用描述
    observation: str             # 工具返回
    final_answer: str = ""       # 若有，则终止


@dataclass
class AgentState:
    question: str
    max_steps: int = 6
    steps: List[StepRecord] = field(default_factory=list)
    messages: List[Dict[str, Any]] = field(default_factory=list)  # OpenAI 格式消息
    done: bool = False
    final_answer: str = ""

    def add_message(self, msg: Dict[str, Any]) -> None:
        self.messages.append(msg)

    def record(self, step: StepRecord) -> None:
        self.steps.append(step)

    def summary(self) -> str:
        """给交付报告/调试用：每步的 Thought/Action/Observation 摘要。"""
        lines = [f"问题: {self.question}", f"总步数: {len(self.steps)}"]
        for s in self.steps:
            lines.append(f"  Step{s.step}: {s.action} → {s.observation[:60]}")
        if self.final_answer:
            lines.append(f"最终回答: {self.final_answer[:100]}")
        return "\n".join(lines)
