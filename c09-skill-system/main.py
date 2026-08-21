"""C09: a tiny, deterministic Skill host for teaching purposes."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parent
SKILL_DIR = ROOT / "skills" / "markdown-quality"
VALIDATOR = SKILL_DIR / "scripts" / "validate.py"
SAMPLES = ROOT / "samples"


def read_frontmatter(skill_file: Path) -> dict[str, str]:
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"missing frontmatter: {skill_file}")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError(f"unterminated frontmatter: {skill_file}")
    metadata: dict[str, str] = {}
    for line in text[4:end].splitlines():
        key, separator, value = line.partition(":")
        if separator:
            metadata[key.strip()] = value.strip().strip('"')
    if not metadata.get("name") or not metadata.get("description"):
        raise ValueError(f"name and description are required: {skill_file}")
    return metadata


def discover_skills() -> list[tuple[Path, dict[str, str]]]:
    return [
        (skill_file, read_frontmatter(skill_file))
        for skill_file in (ROOT / "skills").glob("*/SKILL.md")
    ]


def matches(description: str, request: str) -> bool:
    terms = {term.lower() for term in re.findall(r"[a-z0-9-]+", description)}
    request_terms = {term.lower() for term in re.findall(r"[a-z0-9-]+", request)}
    return bool(terms & request_terms) or "markdown" in request.lower()


def run_validator(sample: Path) -> tuple[int, str]:
    completed = subprocess.run(
        [sys.executable, str(VALIDATOR), str(sample)],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def main() -> int:
    request = "请检查这篇 Markdown 文章的格式"
    skills = discover_skills()
    for _, metadata in skills:
        print(f"[discover] {metadata['name']}")
    selected = next(
        ((path, metadata) for path, metadata in skills if matches(metadata["description"], request)),
        None,
    )
    if selected is None:
        print("[result] status=NO_MATCH")
        return 1
    skill_file, metadata = selected
    print(f"[match] {metadata['name']}")
    skill_text = skill_file.read_text(encoding="utf-8")
    if "references/checklist.md" not in skill_text:
        print("[result] status=INVALID_SKILL")
        return 1
    print("[load] SKILL.md + references/checklist.md")
    passed, failed = 0, 0
    for sample_name in ("good.md", "bad.md"):
        code, output = run_validator(SAMPLES / sample_name)
        if code == 0:
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
