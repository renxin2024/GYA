"""C09: a tiny Skill host that executes the steps declared in SKILL.md.

The host itself knows nothing about "markdown quality". It only knows how to:
  1. discover SKILL.md files and read their frontmatter (name / description / steps);
  2. match a request against a skill's description;
  3. load the matched skill's declared resources (ref) and commands (run);
  4. execute the steps in order and report the deterministic validator's verdict.

All the "what to check" and "how to check" knowledge lives in the skill's own
files (SKILL.md, references/, scripts/), not in this host. That is the whole
point of the lesson: the method is pulled out of the host and into files.

Only the Python standard library is used, so the demo runs with no
third-party dependencies and no API key.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parent
SKILLS_ROOT = ROOT / "skills"
SAMPLES = ROOT / "samples"


def read_frontmatter(skill_file: Path) -> dict:
    """Parse a SKILL.md's frontmatter into a dict.

    Returns {name, description, steps} where `steps` is a list of dicts, each
    holding exactly one of `ref` (a resource to load) or `run` (a command to
    execute, with a `{file}` placeholder for the target file).

    The parser is deliberately minimal — it handles the exact frontmatter
    shape used in this demo, not the full YAML spec.
    """
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"missing frontmatter: {skill_file}")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError(f"unterminated frontmatter: {skill_file}")

    metadata: dict = {}
    steps: list[dict] = []
    current: dict | None = None

    for line in text[4:end].splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ref:"):
            current = {"ref": stripped.split(":", 1)[1].strip()}
            steps.append(current)
        elif stripped.startswith("- run:"):
            current = {"run": stripped.split(":", 1)[1].strip()}
            steps.append(current)
        else:
            key, sep, value = line.partition(":")
            if sep and key.strip() in ("name", "description"):
                metadata[key.strip()] = value.strip().strip('"')

    if not metadata.get("name") or not metadata.get("description"):
        raise ValueError(f"name and description are required: {skill_file}")
    metadata["steps"] = steps
    return metadata


def discover_skills() -> list[tuple[Path, dict]]:
    """Scan skills/*/SKILL.md and read each one's frontmatter."""
    found: list[tuple[Path, dict]] = []
    for skill_file in sorted(SKILLS_ROOT.glob("*/SKILL.md")):
        found.append((skill_file, read_frontmatter(skill_file)))
    return found


def matches(description: str, request: str) -> bool:
    """A deliberately naive matcher: overlap of word tokens.

    This is NOT how a real LLM routes to a skill; it only demonstrates that
    discovery uses `description`, not the skill body, as the signal.
    """
    terms = {term.lower() for term in re.findall(r"[a-z0-9-]+", description)}
    request_terms = {term.lower() for term in re.findall(r"[a-z0-9-]+", request)}
    return bool(terms & request_terms)


def main() -> int:
    request = "请检查这篇 Markdown 文章的格式"

    # 1. discover: read only each skill's frontmatter (name + description + steps)
    skills = discover_skills()
    for skill_file, metadata in skills:
        print(f"[discover] {metadata['name']}")

    # 2. match: pick the skill whose description overlaps the request
    selected = next(
        ((sf, md) for sf, md in skills if matches(md["description"], request)),
        None,
    )
    if selected is None:
        print("[result] status=NO_MATCH")
        return 1
    skill_file, metadata = selected
    skill_dir = skill_file.parent
    print(f"[match] {metadata['name']}")

    # 3. load + execute: run the steps the skill itself declares, in order
    validator_cmd = None
    for step in metadata["steps"]:
        if "ref" in step:
            print(f"[load] {step['ref']}")
        elif "run" in step:
            validator_cmd = step["run"]

    # 4. validate: run the declared command against one good and one bad sample
    if validator_cmd is None:
        print("[result] status=INVALID_SKILL")
        return 1

    passed, failed = 0, 0
    for sample_name in ("good.md", "bad.md"):
        sample = SAMPLES / sample_name
        # The skill declares its own command; the host only fills in {file}.
        argv = validator_cmd.replace("{file}", str(sample)).split()
        print(f"[run] {' '.join(argv)}")
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            cwd=str(skill_dir),
        )
        output = (completed.stdout + completed.stderr).strip()
        if completed.returncode == 0:
            passed += 1
        else:
            failed += 1
        print(f"[validate] {sample_name} -> {output}")

    if passed != 1 or failed != 1:
        print("[result] status=FAIL")
        return 1

    print("[validate] passed=1 failed=1 (expected)")
    print("[result] status=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
