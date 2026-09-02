# C02：Function Calling 单轮闭环

这个示例沿一次天气查询展示完整调用链：

1. Python 把用户消息和工具说明发给模型；
2. 模型返回 `tool_calls`；
3. Python 校验并执行 `get_weather()`；
4. Python 把工具结果作为 `role=tool` 回传；
5. 模型基于结果生成最终回答。

模型只生成调用请求，真正执行函数的是 Python 程序。天气函数返回本地固定的天气演示数据，不代表实时天气。

## 环境

- Python 3.10+
- `openai==2.43.0`
- DeepSeek API Key

```bash
python3 -m pip install -r requirements.txt
export LLM_API_KEY="你的 Key"
export LLM_MODEL="deepseek-v4-flash"
```

也可以继续使用 `DEEPSEEK_API_KEY`。

## 运行

```bash
python3 main.py
```

预期输出顺序：

```text
模型请求：get_weather({"city":"北京"})
程序执行：多云，25℃，东北风3级
模型回答：……
```

模型最终措辞可能变化。验收重点是 `模型请求 → 程序执行 → 模型回答` 三步顺序完整。

## 离线测试

```bash
python3 -m unittest -v test_main.py
```

测试覆盖正常工具调用、未知工具和多余参数。离线测试只验证程序控制流，不能替代真实模型调用。

Java 21 等价实现位于 GYA-Java 仓库的 `c02-function-calling` 模块。
