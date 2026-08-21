"""Deterministic checks used by the markdown-quality Skill."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def validate(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        errors.append("frontmatter must be delimited by ---")
    else:
        frontmatter = text[4 : text.find("\n---\n", 4)]
        for field in ("title", "description"):
            if not re.search(rf"^{field}:\s*.+$", frontmatter, re.MULTILINE):
                errors.append(f"missing frontmatter field: {field}")
    h1_count = len(re.findall(r"^# [^#].*$", text, re.MULTILINE))
    if h1_count != 1:
        errors.append(f"expected exactly one H1, found {h1_count}")
    if not re.search(r"^## 总结\s*$", text, re.MULTILINE):
        errors.append("missing closing section: ## 总结")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python3 validate.py <markdown-file>")
        return 2
    errors = validate(Path(sys.argv[1]))
    if errors:
        print("FAIL: " + "; ".join(errors))
        return 1
    print("PASS: frontmatter=ok h1=1 summary=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
