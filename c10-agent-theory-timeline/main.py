"""C10: a small ReAct loop with an offline replay and optional live mode."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from dataclasses import dataclass


FEWSHOT = """Example 1:
Question: What is 2 + 2?
Thought: I can answer this with the calculator tool.
Action: calculator({\"expression\": \"2 + 2\"})
Observation: 4
Thought: I have the result.
Final Answer: 2 + 2 = 4.

Example 2:
Question: Who wrote Hamlet?
Thought: I need an external fact.
Action: lookup({\"query\": \"author of Hamlet\"})
Observation: William Shakespeare wrote Hamlet.
Thought: I have the fact.
Final Answer: Hamlet was written by William Shakespeare.
"""


SYSTEM = """You are a ReAct agent. Alternate reasoning and action.
Use exactly one line for each field: Thought, Action, Observation, Final Answer.
Available action: lookup({\"query\": \"...\"}).
If you use an Action, wait for the Observation before answering.
"""


LOCAL_FACTS = {
    "capital of france": "Paris is the capital and most populous city of France.",
    "author of hamlet": "William Shakespeare wrote Hamlet.",
}


@dataclass
class Trace:
    actions: int = 0
    observations: int = 0
    terminated: str = ""


def lookup(query: str) -> str:
    normalized = query.lower().strip()
    if normalized in LOCAL_FACTS:
        return LOCAL_FACTS[normalized]
    return "No local fact found."


def parse_action(text: str) -> tuple[str, dict[str, str]] | None:
    match = re.search(r"Action:\s*lookup\((\{.*?\})\)", text)
    if not match:
        return None
    return "lookup", json.loads(match.group(1))


def offline_model(question: str, observation: str | None) -> str:
    if observation is None:
        return (
            "Thought: I need an external fact before answering.\n"
            "Action: lookup({\"query\": \"capital of France\"})"
        )
    return f"Thought: I have the external fact.\nFinal Answer: The answer is {observation}"


def live_model(question: str, history: list[dict[str, str]]) -> str:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required for --live")
    payload = {
        "model": os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
        "messages": [
            {"role": "system", "content": SYSTEM + "\n" + FEWSHOT},
            *history,
            {"role": "user", "content": question},
        ],
        "temperature": 0,
        "stream": False,
    }
    request = urllib.request.Request(
        os.environ.get("LLM_API_URL", "https://api.deepseek.com/chat/completions"),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())["choices"][0]["message"]["content"]


def run(question: str, live: bool = False) -> Trace:
    trace = Trace()
    history: list[dict[str, str]] = []
    observation = None
    for _ in range(3):
        output = live_model(question, history) if live else offline_model(question, observation)
        if "Final Answer:" in output:
            print(f"[Final Answer] {output.split('Final Answer:', 1)[1].strip()}")
            trace.terminated = "final_answer"
            return trace
        action = parse_action(output)
        if action is None:
            raise RuntimeError(f"cannot parse model output: {output}")
        name, arguments = action
        trace.actions += 1
        print(f"[Thought] {output.split('Action:', 1)[0].replace('Thought:', '').strip()}")
        print(f"[Action] {name}({json.dumps(arguments, ensure_ascii=False)})")
        observation = lookup(arguments["query"])
        trace.observations += 1
        print(f"[Observation] {observation}")
        history.extend([
            {"role": "assistant", "content": output},
            {"role": "tool", "content": observation},
        ])
    trace.terminated = "max_steps"
    raise RuntimeError("maximum steps exceeded")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="call a real compatible model")
    args = parser.parse_args()
    trace = run("What is the capital of France?", live=args.live)
    print(f"[check] actions={trace.actions} observations={trace.observations} terminated={trace.terminated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
