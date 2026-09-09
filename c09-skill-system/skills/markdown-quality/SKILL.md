---
name: markdown-quality
description: Check Markdown articles for required frontmatter, one H1 title, and a closing summary. Use when reviewing Markdown article structure or blog drafts.
steps:
  - ref: references/checklist.md
  - run: python3 scripts/validate.py {file}
---

# Markdown quality

Use this Skill when a user asks for a structural check of a Markdown article.

## 步骤

1. 先读 `references/checklist.md`，了解要检查哪些规则。
2. 对目标文件运行 `scripts/validate.py <markdown-file>`，得到确定性的检查结果。
3. 对每条失败的规则，报告文件路径和一条可操作的修复建议。
4. 未经用户明确要求，不要修改文章。

## 边界

`validate.py` 只回答「结构是否符合规则」，是确定性校验；「文章写得好不好」是语义判断，交给模型，不在这个 Skill 内。
