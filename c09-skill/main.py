"""C09：最小 Skill 加载器。"""

from pathlib import Path


def load_skill(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("Skill must start with front matter")
    header, body = text.split("---\n", 2)[1:]
    values: dict[str, str] = {"instructions": body.strip()}
    for line in header.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def run(skill: dict[str, str], task: str) -> str:
    if skill.get("name") != "release-note":
        raise ValueError(f"unsupported skill: {skill.get('name')}")
    return f"{skill['instructions']}\n任务：{task}\n结果：先列出变更，再列出验证证据。"


if __name__ == "__main__":
    skill = load_skill(Path(__file__).parent / "skills/release-note/SKILL.md")
    print(f"[1] 发现 Skill: {skill['name']} v{skill['version']}")
    print(f"[2] 加载指令: {len(skill['instructions'])} 字符")
    print("[3] 执行结果:")
    print(run(skill, "总结本次小版本的变更"))
