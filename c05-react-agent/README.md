# C05 演示：手写 ReAct Agent——循环的诞生

一个最小但完整的四文件 ReAct Agent：模型"想"（Thought + Action），代码"做"（执行工具）+ "看"（Observation 回喂），循环直到 Final Answer。

## 文件结构

```
c05-react-agent/
├── main.py        # CLI 入口（单问题 / -i 交互模式）
├── react_loop.py  # ReAct 主循环（Agent 核心引擎）
├── tools.py       # 工具系统（复用 C04 的 ToolRegistry + ToolResponse）
└── state.py       # 状态管理（对话历史 + 步骤记录 + 终止条件）
```

## 前置环境

| 项 | 要求 |
|----|------|
| Python | 3.10+（`python3 --version` 查看） |
| 依赖 | 无（只用标准库，不需要 pip install） |
| API Key | DeepSeek 官方 Key（与 C01-C04 相同） |

## 运行

```bash
export DEEPSEEK_API_KEY=sk-你的key
python3 main.py                              # 默认演示任务
python3 main.py "北京天气怎么样？顺便算一下 123*456"   # 自定义任务
python3 main.py -i                           # 交互模式
```

## 预期输出（关键部分）

```
=== Step 1 ===
[Thought] The user wants three things: check weather, calculate, summarize...
[Action] 调用 get_weather({"city": "北京"})
[Observation] 北京: 多云，25℃，东北风 3 级
[Action] 调用 calculator({"expression": "123*456"})
[Observation] 56088

=== Step 2 ===
[Thought] I have both results. Now I'll summarize them into one sentence.
[Final Answer] 北京今天多云，气温25℃；123 × 456 = 56088。
```

（模型名、措辞可能略有不同，但循环形状一致：工具调用 → 观察 → 再决策 → 最终回答。）

## 它证明的事

1. **所有 Agent 框架的本质 = while 循环**：LLM(问题+历史) → Action → Observation → 再问 LLM，直到模型说"不需要工具了"
2. **模型负责"想"，代码负责"做"**：`reasoning_content` 是 Thought（思考），`tool_calls` 是 Action（行动），注册表执行是 Observation（观察）
3. **"自主决策"来自循环，不是模型意志**：模型只是每次根据"问题 + 已有结果"预测下一步；循环让多步决策成为可能
4. **终止条件很重要**：`max_steps` 上限 + "无 tool_calls 即完成"——防止死循环

## 常见坑

1. **Q: HTTP 400 `reasoning_content` 错误？**
   A: DeepSeek thinking 模式下，回喂 assistant 消息必须**原样**包含 `reasoning_content`。代码里 `state.add_message(msg)` 直接回传完整消息。
2. **Q: 模型一直调用同一个工具停不下来？**
   A: 这是循环没有终止条件的典型症状。`max_steps` 上限 + 每次把 Observation 回喂，模型看到"已查过"通常就会收敛。生产里还会加"重复调用检测"。
3. **Q: 模型直接回答而不调工具？**
   A: 如果任务其实不需要工具（如"写首诗"），这是正确行为——"不需要时不用工具"正是 C03 讲的指令遵循。如果任务需要工具但它不调，检查 schema 描述是否足够清晰。
