---
name: markdown-quality
description: Check Markdown articles for required frontmatter, one H1 title, and a closing summary. Use when reviewing Markdown article structure or blog drafts.
---

# Markdown quality

Use this Skill when a user asks for a structural check of a Markdown article.

1. Read `references/checklist.md` before checking a file.
2. Run `scripts/validate.py <markdown-file>` for deterministic checks.
3. Report each failed rule with the file path and a concrete fix.
4. Do not modify the article unless the user explicitly asks for a fix.
