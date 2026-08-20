# C04 演示：工具注册表与 ToolResponse 协议

一个演示「工具多了以后的正规管理方式」的最小程序：ToolRegistry（注册/发现/调用/下线）+ ToolResponse（status/text/data/error_info 结构化响应）。

对比 C02 的硬编码分发（`if name == "get_weather"`）：加工具要改代码重启；本篇的注册表加工具 = 注册一个函数，调用方代码零改动。

## 前置环境

| 项 | 要求 |
|----|------|
| Python | 3.10+（`python3 --version` 查看） |
| 依赖 | 无（只用标准库，不需要 pip install） |
| API Key | DeepSeek 官方 Key（与 C01-C03 相同） |

## 获取 API Key（约 2 分钟）

1. 打开 https://platform.deepseek.com 注册/登录
2. 左侧「API Keys」→「创建 API Key」，复制 `sk-...`
3. （按量付费需先充值：控制台「充值」最低 10 元）

## 运行

```bash
export DEEPSEEK_API_KEY=sk-你的key
python3 registry_demo.py
```

## 预期输出（关键部分）

```
已注册工具: ['get_weather', 'calculator', 'search_notes']

[1] 正常闭环：模型从 schema 发现工具并调用
  [模型说] 调用 get_weather({"city": "北京"})
  [注册表] status=SUCCESS, text=北京: 多云，25℃，东北风 3 级
  [模型说] 调用 calculator({"expression": "123*456"})
  [注册表] status=SUCCESS, text=56088

[2] 错误处理：调用不存在的工具（模拟模型幻觉）
status=ERROR, error_code=UNKNOWN_TOOL

[3] 错误处理：参数不对（calculator 缺 expression）
status=ERROR, error_code=INVALID_PARAM

[4] 下线工具：unregister('get_weather')
现在问天气，模型会怎么做？
[模型直接回答] 很抱歉，我目前没有查询实时天气的工具...
```

（模型名、措辞可能略有不同，但四个场景的形状一致。）

## 它证明的事

1. **注册表 = 加工具不改调用方代码**：`register()` 一个函数 + schema，模型就能发现并调用它
2. **ToolResponse = 错误从"靠猜"变"读字段"**：`status` + `error_info.code` 让程序直接判断，不再靠正则/文本猜测
3. **下线 = 模型自然不再调用**：`unregister()` 后 schema 里没有它，模型会老老实实说"没有这个工具"
4. **这是 MCP 的前身**：MCP 本质是把本地单机注册表扩展成网络协议（tools/list → 动态获取工具）

## 常见坑

1. **Q: 输出报 HTTP 400 `reasoning_content` 错误？**
   A: DeepSeek thinking 模式下，回喂 assistant 消息必须**原样**包含 `reasoning_content`。代码里 `messages.append(msg)` 直接回传完整消息即可，不要手动重建只有 tool_calls 的字典。
2. **Q: 模型一次输出多个 tool_calls 时报错？**
   A: assistant 消息（含全部 tool_calls）只 append **一次**，然后每个 tool_call 结果各 append 一条 `role=tool` 消息。
3. **Q: `[模型总结] None`？**
   A: 确认第二轮调用取的是 `message.content`（demo 的 `call()` 返回 message 对象），不是完整响应的 `choices[0].message.content`。
