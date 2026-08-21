# C09 Skill 系统最小演示

这个 demo 用纯 Python 标准库模拟一个极小的 Skill Host：扫描 `SKILL.md`、根据 description 匹配请求、按需加载资源，并调用确定性脚本校验 Markdown 文件。

它不是完整的 LLM Agent，也不模拟模型推理。目的是把 Skill 的文件结构、发现、加载和验证边界拆开。

## 环境

- Python 3.10+
- 无第三方依赖
- 不需要 API Key

## 运行

```bash
python3 main.py
```

预期最后一行：

```text
[result] status=PASS
```
