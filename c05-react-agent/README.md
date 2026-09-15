# C05 演示：最小 ReAct Runtime——循环的诞生

模型“想”（Thought + Action），代码“做”（执行工具）+ “看”（Observation 回喂），循环直到 Final Answer。

任务是“公司总部今天的天气”——它天然需要两步：先把“公司总部”解析成城市，再用这个城市查天气。工具是三个本地确定性只读夹具（不依赖外部 API，避免网络和额度污染控制流证据）：

| 工具 | 作用 | 行为 |
| --- | --- | --- |
| `resolve_company_address` | 解析总部地址 | 上海总部→上海，北京总部→北京，其余→待澄清 |
| `get_weather` | 查城市天气 | 上海→小雨 22℃，北京→晴 18℃ |
| `request_clarification` | 信息不足时请求补充 | 无副作用 |

## 运行

### Python（3.10+）

```bash
# 离线回归（3 项，不需要 Key）
python3 -m unittest test_react_agent.py

# 真实模型路径，Key 只从环境变量读
export LLM_API_URL='https://your-openai-compatible-endpoint/v1/chat/completions'
export LLM_API_KEY='your-key'
export LLM_MODEL='your-model'
python3 react_agent.py
```

### Java（21 + Gradle）

```bash
gradle run --args="--offline"   # 离线验收，看到 ALL_OFFLINE_CHECKS_PASSED 即通过
gradle run                      # 真实模型路径，环境变量同上
```

离线回归的 3 项里，包含“参数错误成为 `ERROR` Observation 后，模型修正并完成”和“重复决策到达 `MAX_STEPS`”。

## 完整输出记录

文章第四节引用的对照 Trace，由真实模型跑出：

```text
上海：resolve_company_address({"company_name": "上海总部"})
  → 看到 RESOLVED(city="上海")
  → get_weather({"city": "上海"})

北京：resolve_company_address({"company_name": "北京总部"})
  → 看到 RESOLVED(city="北京")
  → get_weather({"city": "北京"})
```

两步之间参数随 Observation 改变，这正是 ReAct 与「固定脚本多跑几遍」的分水岭。

## 目录

- `react_agent.py` / `test_react_agent.py`：配套实现（Python）
- `legacy/`：早期四文件版本（`main.py` / `react_loop.py` / `state.py` / `tools.py`），与文章不对应，仅供追溯

Java 对照实现见 [GYA-Java 的 c05 目录](https://github.com/renxin2024/GYA-Java/tree/main/c05-react-agent)。
