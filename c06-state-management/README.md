# C06 演示：状态管理——从手写状态机到 StateGraph

同一个任务用两种方式实现，跑出相同结果：
- **state_machine.py**：手写状态机（State dict + Node 函数 + Edge 路由表，零依赖）
- **langgraph_demo.py**：LangGraph StateGraph（声明式图，同一个 State/Node/Edge 概念）

核心演示：**图管流程，LLM 管内容**——路由是确定性代码（不走 LLM、零 token），LLM 只在"语义理解"和"总结"两个节点被调用。

## 前置环境

| 项 | 要求 |
|----|------|
| Python | 3.10+ |
| 依赖 | 手写版无；LangGraph 版需要 `pip install langgraph`（或用 `uv run --with langgraph`） |
| API Key | DeepSeek 官方 Key（与 C01-C05 相同） |

## 运行

```bash
export DEEPSEEK_API_KEY=sk-你的key

# 手写状态机（零依赖）
python3 state_machine.py

# LangGraph 版
uv run --with langgraph python3 langgraph_demo.py
# 或 pip install langgraph && python3 langgraph_demo.py
```

## 预期输出（两版相同）

```
[手写版] === Node: parse_intent ===  intent=['get_weather', 'calculator']
         === Node: execute_tools ===  get_weather → 多云，25℃，东北风 3 级
                                      calculator → 56088
         === Node: summarize ===      北京天气多云、25℃...

[LangGraph 版] 同样的三节点流转，输出一致
最终答案: 北京天气多云、25℃；123×456 的结果是 56088。
```

## 它证明的事

1. **手写状态机 = StateGraph 的雏形**：State（dict）/ Node（函数）/ Edge（路由表）三件套，LangGraph 只是把它们声明式化
2. **图管流程，LLM 管内容**：路由是确定性的 Python 代码（`next_step` 字段 / conditional edge），不消耗 token；LLM 只在需要语义的节点（parse_intent / summarize）被调用
3. **ReAct 是 StateGraph 的特例**：通用图框架可以表达任意工作流，ReAct 只是其中一种三节点循环

## 常见坑

1. **Q: `uv run --with langgraph` 装包慢？**
   A: 首次会下载依赖（约 30 秒），之后有缓存。`pip install langgraph` 也可以。
2. **Q: LangGraph 版本 API 变了？**
   A: 本文按 langgraph 1.x 编写（`StateGraph` / `add_node` / `add_edge` / `add_conditional_edges` / `compile` / `invoke`）。老版本 0.x 的 `END` 导入路径可能不同，看官方文档。
3. **Q: 手写版为什么不用递归而是 while？**
   A: 递归受 Python 调用栈限制（默认 ~1000 层），while 循环可以跑任意步。框架内部也是循环，不是递归。
