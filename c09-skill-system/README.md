# C09 Skill 系统最小演示

这个 demo 用纯 Python 标准库模拟一个极小的 Skill Host。关键点在于：**Host 自己不知道什么叫「Markdown 质量」**，它只做四件通用的事——发现 Skill、按 `description` 匹配、加载 Skill 声明的资源、执行 Skill 声明的命令。真正的「检查什么、怎么检查」全部写在 Skill 自己的文件里。

## 职责拆在哪

| 谁 | 知道什么 | 不知道什么 |
|---|---|---|
| `main.py`（Host） | 怎么发现 SKILL.md、怎么读 frontmatter、怎么匹配、怎么按步骤执行 | 「Markdown 质量」具体指什么 |
| `skills/markdown-quality/SKILL.md` | 这个 Skill 叫什么、解决什么问题、步骤顺序（先读 checklist 再跑 validate） | 校验规则的实现细节 |
| `references/checklist.md` | 要检查哪些规则 | 怎么用代码去查 |
| `scripts/validate.py` | 怎么用代码逐条校验 | 什么时候该用它、结果怎么上报 |

`SKILL.md` 的 frontmatter 里有一份 `steps` 列表，每步要么是 `ref:`（加载一个资源文件），要么是 `run:`（执行一条命令，`{file}` 是目标文件的占位符）。Host 读取这份 `steps` 并逐条执行——**步骤从文件里来，不是写死在 Host 里**。

它不是完整的 LLM Agent，也不模拟模型推理。目的只是把「发现—匹配—加载—执行—验收」这条边界摊开，让读者看到「方法」是怎样从 Host 拆到文件里的。

## 环境

- Python 3.9+
- 无第三方依赖
- 不需要 API Key

## 运行

```bash
python3 main.py
```

## 预期输出

```text
[discover] markdown-quality
[match] markdown-quality
[load] references/checklist.md
[run] python3 scripts/validate.py .../samples/good.md
[validate] good.md -> PASS: frontmatter=ok h1=1 summary=ok
[run] python3 scripts/validate.py .../samples/bad.md
[validate] bad.md -> FAIL: frontmatter must be delimited by ---; missing closing section: ## 总结
[validate] passed=1 failed=1 (expected)
[result] status=PASS
```

注意最后一行 `status=PASS` 的含义：它不表示两份样例都合格，而是 Host 的验收条件被满足——合格样例通过、故意损坏的样例被拦截。「验证器工作正常」和「被验证对象合格」是两回事。
