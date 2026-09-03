# C03：模型为什么能生成工具调用请求？

本章不执行订单操作。它用“已支付退款 / 未支付取消 / 信息不足 / 无意图”四类虚构订单场景，比较 Prompt-only 与 Native tools 两种接口路径。

模型只生成候选调用；Runtime 提供已验证状态，并负责后续的业务校验、授权、确认和执行。本 demo 没有退款、取消或查询订单的实现。

## 运行

```bash
python3 -m unittest -v test_main.py
python3 main.py --dry-run

export LLM_API_KEY='你的 Key'
python3 main.py --mode all --case all
```

通过标准：已支付退款应输出 `refund_order(O-100)`；未支付取消应输出 `cancel_order(O-200)`；信息不足和无意图时没有工具调用。`--description-profile swapped` 只对调 description，是故障注入，不能用于生产。

旧版 `train_compare.py` 的多城市天气实验不再代表本章结论，已由上述单轮订单 fixture 实验替代。

一个演示「工具调用格式能力来自**后训练 + API 层**，而不是你在 prompt 里写几句『请输出 JSON』」的最小程序。

同一个问题（北京和上海天气，需要两个工具调用），三种问法对比：

| 方式 | 输出 | 说明 |
|------|------|------|
| **A) 裸问**（无 tools） | 一段长篇文本回答"我无法实时获取天气" | 模型只知道文本补全，不知道『可以用』工具 |
| **B) 带 tools 参数** | 2 个结构化 `tool_calls`，各带独立 id | 后训练教出的格式约定 + API 层注入保证 |
| **C) 纯 prompt 手写格式** | 靠 system prompt 要求"输出 JSON"，无 API 保证 | 多次运行会漏调用、格式不稳，调用方要靠正则"捞" |

实测（deepseek-v4-flash，2026-08-20）：方式 B **5/5** 次完整输出两个 tool_calls；方式 C 只有 **3/5** 次能被解析器完整捞到（其余漏掉一个城市）。

## 前置环境

| 项 | 要求 |
|----|------|
| Python | 3.10+（`python3 --version` 查看） |
| 依赖 | 无（只用标准库，不需要 pip install） |
| API Key | DeepSeek 官方 Key（与 C01/C02 相同） |

## 获取 API Key（约 2 分钟）

1. 打开 https://platform.deepseek.com 注册/登录
2. 左侧「API Keys」→「创建 API Key」，复制 `sk-...`
3. （按量付费需先充值：控制台「充值」最低 10 元）

## 运行

```bash
export DEEPSEEK_API_KEY=sk-你的key
python3 train_compare.py
```

## 预期输出（关键部分）

```
[A] 不带 tools 参数（模型只会文本补全）
content: '很抱歉，我无法直接接入实时的气象数据中心...'
tool_calls: None

[B] 带 tools 参数（API 层注入 + 后训练格式约定）
tool_calls: [ {name: get_weather, arguments: {"city": "北京"}}, ... ]

[C] 不带 tools 参数，只靠 system prompt 要求输出 JSON（跑 5 次）
第1次: 解析到 2 个工具调用 ✓ 数量正好
...
第5次: 解析到 1 个工具调用 ✗ 漏了 1 个

[D] 稳定性对比
方式 B（带 tools 参数）: 5/5 次输出完整的 2 个 tool_calls
方式 C（纯 prompt 手写）: 3/5 次能被解析器完整捞到 2 个调用
```

（模型名、具体次数可能随模型版本变化，但形状一致：**B 稳定、C 会漏**。）

## 它证明的事

1. **模型不知道『可以用』工具**——除非你把工具定义通过 `tools` 参数（或 prompt 文本）告诉它。
2. **带 tools 参数 = 后训练教出的格式 + API 层保证**——结构化 `tool_calls` 数组、独立 id、参数校验，是 API 层的产品能力，调用方直接执行即可。
3. **纯 prompt 手写格式靠模型的『自觉』**——它尽力遵守，但没有 API 层校验，多个工具调用时会漏、会裹进散文，调用方得写正则去"捞"。
4. **这正是『有的模型有 tool calling API、有的没有』的原因**：差别不在数学结构，在后训练阶段有没有用工具调用序列做 fine-tune，以及 API 层有没有提供结构化接口。

## 常见坑

1. **Q: 输出里 model 显示 `deepseek-v4-flash`，但我想用别的模型？**
   A: 设 `export LLM_MODEL=你的模型名` 覆盖。
2. **Q: 方式 C 这次 5/5 全对？**
   A: 正常——deepseek-v4-flash 对简单场景靠 prompt 也能稳住。多跑几次或换更复杂的多工具场景，漏调用就会出现（这正是演示想说明的：**不稳定**）。
