"""C11 暂停协议：LLM 客户端接口。

- LlmClient 是统一契约：三种控制器只依赖 complete_json / calls / usage。
- RealLlmClient 调用真实模型，依赖在 __init__ 里才访问环境变量，
  离线测试 import 本模块不会触发网络或 Key 要求。
- FixtureLlmClient 是确定性夹具：只验证控制流（Runtime 迁移、调度停止、Trace 契约），
  **不能**证明真实模型行为。真实模型证据必须另行运行并如实报告。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Tuple


class LlmClient:
    def complete_json(self, purpose: str, system: str, user: str) -> Dict[str, Any]:
        raise NotImplementedError

    @property
    def calls(self) -> int:
        raise NotImplementedError

    @property
    def usage(self) -> Dict[str, int]:
        raise NotImplementedError


class RealLlmClient(LlmClient):
    """通过 OpenAI 兼容 Chat Completions 接口调用真实模型。

    只读取环境变量，不打印密钥、不拼接含凭证的地址到日志。
    参数（thinking / response_format）需按实际服务方文档确认支持。
    """

    def __init__(self) -> None:
        self.api_key = os.environ.get("LLM_API_KEY", "") or os.environ.get(
            "DEEPSEEK_API_KEY", ""
        )
        self.model = os.environ.get("LLM_MODEL", "")
        self.api_url = self._chat_url(os.environ.get("LLM_API_URL", ""))
        if not self.api_key or not self.model or not self.api_url:
            raise RuntimeError("真实调用需要 LLM_API_URL、LLM_MODEL 与 LLM_API_KEY/DEEPSEEK_API_KEY")
        # 本 demo 需要模型直接输出可解析的 JSON 决定，不消费推理过程。
        # deepseek-v4-flash 是推理模型：默认会把大量 token 花在 reasoning_content 上，
        # max_tokens 过低时 content 会被截断为空。通过 thinking disabled 跳过推理阶段，
        # 这是 DeepSeek V4 官方参数，不是所有 OpenAI 兼容接口的通用保证（见 README）。
        self._disable_thinking = os.environ.get("LLM_DISABLE_THINKING", "1") != "0"
        self._calls = 0
        self._usage: Dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    @staticmethod
    def _chat_url(value: str) -> str:
        value = value.rstrip("/")
        if not value:
            return ""
        if value.endswith("/chat/completions"):
            return value
        return value + "/chat/completions"

    def complete_json(self, purpose: str, system: str, user: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            # 推理模型下 max_tokens 同时限制 reasoning 与最终 content；
            # 即便关闭推理，决定内容也可能较长，给足空间避免 content 被截断。
            "max_tokens": 4096,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        if self._disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"LLM HTTP {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"LLM network error: {error.reason}") from error

        self._calls += 1
        response_usage = body.get("usage") or {}
        for key in self._usage:
            self._usage[key] += int(response_usage.get(key) or 0)

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError(f"LLM response missing content for {purpose}") from error
        if not isinstance(content, str) or not content.strip():
            # 空 content 的常见原因：推理模型的 reasoning 阶段占满 max_tokens，
            # 最终 content 被截断。区分「推理占满」与「其他错误」再提示，不盲目归因。
            finish_reason = body["choices"][0].get("finish_reason")
            reasoning_tokens = (
                body.get("usage", {})
                .get("completion_tokens_details", {})
                .get("reasoning_tokens", 0)
            )
            if finish_reason == "length" and reasoning_tokens > 0:
                raise RuntimeError(
                    f"LLM empty content for {purpose}: reasoning 阶段占满 max_tokens"
                    f"（finish_reason=length, reasoning_tokens={reasoning_tokens}）。"
                    "应增大 max_tokens，或对本推理模型关闭 thinking。"
                )
            raise RuntimeError(
                f"LLM returned empty content for {purpose} (finish_reason={finish_reason})"
            )
        return extract_json_object(content)

    @property
    def calls(self) -> int:
        return self._calls

    @property
    def usage(self) -> Dict[str, int]:
        return dict(self._usage)


_BRIEF_CONTENT = "决策粒度不同的控制模式；审批边界由运行时准入保证。"

_READY_QUESTION = "创作纲领已生成，是否继续生成正文草稿？"

# 夹具的默认 ReAct 序列：每一步都在回应上一步的观察。
# 序列走完后重复最后一条（等待信号）——这样「不识别等待信号的执行器」会一直转，
# 而不是靠一条 FINISH 意外停下来。
DEFAULT_REACT_DECISIONS: Tuple[Dict[str, Any], ...] = (
    {"type": "EXECUTE_TOOL", "action": "search_materials", "args": {"query": "控制模式"}},
    {"type": "EXECUTE_TOOL", "action": "read_material", "args": {"material_id": "material_1"}},
    {"type": "EXECUTE_TOOL", "action": "read_material", "args": {"material_id": "material_2"}},
    {
        "type": "EXECUTE_TOOL",
        "action": "create_brief",
        "args": {"content": _BRIEF_CONTENT, "evidence_ids": ["material_1", "material_2"]},
    },
    {"type": "REQUEST_USER_INPUT", "question": _READY_QUESTION},
)

DEFAULT_PLAN_STEPS: Tuple[Dict[str, Any], ...] = (
    {"type": "EXECUTE_TOOL", "action": "search_materials", "args": {"query": "控制模式"}},
    {"type": "EXECUTE_TOOL", "action": "read_material", "args": {"material_id": "material_1"}},
    {"type": "EXECUTE_TOOL", "action": "read_material", "args": {"material_id": "material_2"}},
    {
        "type": "EXECUTE_TOOL",
        "action": "create_brief",
        "args": {"content": _BRIEF_CONTENT, "evidence_ids": ["material_1", "material_2"]},
    },
    {"type": "REQUEST_USER_INPUT", "question": _READY_QUESTION},
    # 等待之后的步骤：正确实现在此之前就挂起了，根本不会走到这一步。
    {"type": "EXECUTE_TOOL", "action": "write_draft", "args": {"content": "正文草稿"}},
)


class FixtureLlmClient(LlmClient):
    """确定性离线夹具：只验证控制流，不能证明真实模型行为。

    - react：按 DEFAULT_REACT_DECISIONS 依次提出决定（可用 react_decisions 覆盖）。
    - plan：返回一份决定级计划（可用 plan_steps 覆盖）。
    - workflow_content：返回纲领内容（节点内容由模型生成，路由由代码决定）。

    它还记录每次调用的提示词，供测试检查「提示词里有没有被硬编码的资料顺序」。
    """

    def __init__(
        self,
        react_decisions: Optional[Sequence[Dict[str, Any]]] = None,
        plan_steps: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> None:
        self._calls = 0
        self._usage: Dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self.react_decisions: List[Dict[str, Any]] = [
            dict(item) for item in (react_decisions or DEFAULT_REACT_DECISIONS)
        ]
        self.plan_steps: List[Dict[str, Any]] = [
            dict(item) for item in (plan_steps or DEFAULT_PLAN_STEPS)
        ]
        self._react_index = 0
        self.prompts: List[Tuple[str, str, str]] = []

    def complete_json(self, purpose: str, system: str, user: str) -> Dict[str, Any]:
        self.prompts.append((purpose, system, user))
        self._calls += 1

        if purpose == "react":
            if not self.react_decisions:
                raise ValueError("react fixture 序列为空")
            index = min(self._react_index, len(self.react_decisions) - 1)
            self._react_index += 1
            return dict(self.react_decisions[index])

        if purpose == "plan":
            return {"steps": [dict(item) for item in self.plan_steps]}

        if purpose == "workflow_content":
            return {"brief_summary": _BRIEF_CONTENT}

        raise ValueError(f"unknown fixture purpose: {purpose}")

    @property
    def calls(self) -> int:
        return self._calls

    @property
    def usage(self) -> Dict[str, int]:
        return dict(self._usage)


def extract_json_object(text: str) -> Dict[str, Any]:
    """兼容纯 JSON 与 Markdown JSON 代码块，拒绝非对象结果。"""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("模型输出必须是 JSON 对象")
    return value
