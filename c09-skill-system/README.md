# C09 Skill 系统最小演示

这个 demo 用纯 Python 标准库模拟一个极小的 Skill Host：

1. 扫描 Skill 的 `SKILL.md` frontmatter；
2. 根据 `description` 判断请求是否匹配；
3. 匹配后加载 Skill 正文；
4. 按指令调用 `scripts/validate.py`；
5. 输出结构化检查结果。

它不是完整的 LLM Agent，也不模拟模型推理。目的只是把 Skill 的文件结构、发现、按需加载和确定性校验拆开，让读者先看到协议边界。

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
[load] SKILL.md + references/checklist.md
[validate] good.md -> PASS: frontmatter=ok h1=1 summary=ok
[validate] bad.md -> FAIL: frontmatter must be delimited by ---; missing closing section: ## 总结
[validate] passed=1 failed=1 (expected)
[result] status=PASS
```

demo 还会检查一个故意缺少 frontmatter 的失败样例，展示 Skill 的执行结果和脚本校验结果是两层不同的事情。
