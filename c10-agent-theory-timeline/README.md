# C10 ReAct 论文风格最小演示

这个 demo 用两个 few-shot 示例约束模型输出 `Thought / Action / Observation` 轨迹，并在本地工具环境中执行一次完整的 ReAct 循环。

默认使用离线 replay，不需要 API Key；它验证的是 ReAct 的控制流，不冒充论文 benchmark 实验。后续设置 `DEEPSEEK_API_KEY` 后，可以切换到真实模型模式。

## 环境

- Python 3.10+
- 默认模式无第三方依赖、无 API Key
- live 模式需要 `DEEPSEEK_API_KEY`

## 运行

```bash
python3 main.py
```

预期看到：

```text
[Thought] I need an external fact before answering.
[Action] lookup({"query": "capital of France"})
[Observation] Paris is the capital and most populous city of France.
[Final Answer] The capital of France is Paris.
[check] actions=1 observations=1 terminated=final_answer
```

## 真实模型模式

```bash
export DEEPSEEK_API_KEY=sk-...
python3 main.py --live
```

真实模型的输出可能不同；文章只把论文实验结果和本地 replay 输出分开报告。
