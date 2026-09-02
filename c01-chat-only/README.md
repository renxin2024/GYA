# C01：从聊天输出到提示词动作协议

同一个模型、同一个天气问题，连续观察两种运行方式：

1. 普通聊天只打印模型文本，不执行动作；
2. 提示词约定动作 JSON，Python 校验后执行本地 `get_weather()`。

这个 demo 刻意不使用供应商原生 Function Calling。它展示的是原生 `tools` / `tool_calls` 出现前也能实现的最小机制，以及这种机制为什么脆弱。

## 环境

- Python 3.9+
- `openai==2.43.0`
- 一个 OpenAI 兼容的模型 API Key

安装依赖：

```bash
python3 -m pip install -r requirements.txt
```

设置环境变量：

```bash
export LLM_API_KEY="你的 Key"
export LLM_MODEL="deepseek-v4-flash"
export LLM_API_URL="https://api.deepseek.com"
```

`LLM_API_URL` 可以填写 API 根地址，也可以填写以 `/chat/completions` 结尾的完整地址，程序会自动转换成 SDK 所需的根地址。

## 运行

依次运行两种方式：

```bash
python3 main.py
```

也可以单独运行：

```bash
python3 main.py --mode chat
python3 main.py --mode prompt-tool
```

输出形状：

```text
普通聊天输出：……
Python 执行动作：否

--- 加入动作格式提示词后 ---
模型输出动作文本：{"name":"get_weather","arguments":{"city":"北京"}}
Python 执行动作：get_weather({"city": "北京"})
工具返回：多云，25℃，东北风3级
```

模型的普通回答和 JSON 空格可能变化。验收点不是逐字一致，而是第一段没有执行动作，第二段只有在 JSON 通过校验后才进入 Python 工具分支。

天气结果来自本地固定的天气演示数据，不代表北京的实时天气。

Java 21 等价实现只用于双语言验收，正文不重复展开。可从包含 Gradle Wrapper 的 GYA-Java 仓库执行：

```bash
./gradlew :c01-chat-only:test
./gradlew :c01-chat-only:run --args='--mode all'
```

## 离线测试

```bash
python3 -m unittest -v test_main.py
```

测试覆盖合法动作、Markdown 代码围栏、未知动作、多余参数和空城市名。它只验证程序控制流，不能替代真实模型调用。

## 常见失败

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `请先设置 LLM_API_KEY` | 没有配置 Key | 设置 `LLM_API_KEY` 或 `DEEPSEEK_API_KEY` |
| `模型没有返回合法的纯 JSON` | 模型夹带解释或代码围栏 | 收紧提示词，或增加受控提取逻辑；这正是提示词协议的脆弱处 |
| `不允许执行未知动作` | 模型生成了白名单外的名称 | 不要动态反射执行；拒绝并记录 |
| 401、超时或连接失败 | Key、余额、地址或网络异常 | 核对环境变量与供应商控制台 |
