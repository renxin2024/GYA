# C02 演示：Function Calling 第一性原理

一个演示「模型根本没有真正调用工具——它只是输出了一个 JSON，真正执行的是你的代码」的最小程序。

## 前置环境

| 项 | 要求 |
|----|------|
| Python | 3.10+（`python3 --version` 查看） |
| 依赖 | 无（只用标准库，不需要 pip install） |
| API Key | DeepSeek 官方 Key（与 C01 相同，按量付费，充几块钱够跑几十轮） |

Java 21 版等价演示见系列配套的 **GYA-Java** 仓库。

## 获取 API Key（约 2 分钟）

1. 打开 https://platform.deepseek.com 注册/登录
2. 左侧「API Keys」→「创建 API Key」，复制 `sk-...`
3. （按量付费需先充值：控制台「充值」最低 10 元）

## 运行

```bash
export DEEPSEEK_API_KEY=sk-你的key
python3 main.py
```

## 预期输出

```
模型: deepseek-v4-flash
问题: 北京现在天气怎么样？
----------------------------------------------
[模型说] 我要调用工具: get_weather({"city": "北京"})
[调用方] 我已执行工具，结果是: 多云，25℃，东北风 3 级
[模型最后说] 北京现在多云，气温25℃，东北风3级。
```

（模型名和天气措辞可能略有不同，但流程形状一致。）

## 它证明的事

- **模型只会说**：它把「我想查北京天气」编码成一个 JSON（`tool_calls`），并没有真的联网。
- **调用方负责做**：真正去查天气（这里是查一张本地表）的是 `get_weather()`，是**你的代码**在执行。
- **回喂再答**：调用方把工具结果塞回对话，模型基于结果生成最终回答。

## 常见坑

1. **Q: 输出里 model 显示 `deepseek-v4-flash`，但我想用别的模型？**
   A: 设 `export LLM_MODEL=你的模型名` 覆盖。

2. **Q: 报错 `No module named ...` 或 401 `Invalid API key`？**
   A: 确认已经 `export DEEPSEEK_API_KEY=sk-...`（`.env` 里的 Key 需要先 `source .env` 或用 shell 导出）。

3. **Q: 请求超时 / 网络问题？**
   A: DeepSeek API 需要能直连（api.deepseek.com）。跨国网络可能需要代理，把代理地址设到环境变量。

## 文件

- `main.py` — 完整闭环：声明工具 → 模型回 tool_calls → 调用方执行 → 回喂 → 最终回答
- `probe.py` — 探测脚本：对比「无 tools」vs「带 tools」时模型输出形状的根本差异
- `loop.py` — 延伸：把一轮改造成 while 循环（Agent 雏形），支持多工具并行