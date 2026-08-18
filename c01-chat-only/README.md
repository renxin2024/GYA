# C01 演示：只会说话的模型（命令行聊天）

一个 40 行的命令行聊天程序。跑起来之后，你就能亲手体验「模型只会说话」这件事。

## 前置环境

| 项 | 要求 |
|----|------|
| Python | 3.10+（`python3 --version` 查看） |
| 依赖 | 无（只用标准库，不需要 pip install） |
| API Key | DeepSeek 官方 Key（按量付费，充几块钱够聊几百轮） |

## 获取 API Key（约 2 分钟）

1. 打开 https://platform.deepseek.com 注册/登录
2. 左侧「API Keys」→「创建 API Key」，复制 `sk-...`
3. （按量付费需先充值：控制台「充值」最低 10 元）

## 运行

```bash
export DEEPSEEK_API_KEY=sk-你的key
python3 chat.py
```

看到提示后直接输入文字回车，就能对话：

```
你 > 你好，你是谁？
模型 > 你好！我是一个 AI 助手……
你 > 你会查天气吗？
模型 > 我没有实时访问互联网的能力……
你 > exit
```

## 预期输出

- 能连续多轮对话（模型记得前文——因为每次请求都把整个历史发回去了）
- 问「你能查天气/订机票/执行操作吗」→ 模型回答「不能」（它只会生成文本）
- 退出：输入 `exit` / `quit` / `退出`，或 Ctrl+C

## 失败排查

| 报错 | 原因 | 解法 |
|------|------|------|
| `请先设置 DEEPSEEK_API_KEY` | 没设环境变量 | `export DEEPSEEK_API_KEY=sk-...` |
| `401` / `Authentication Fails` | Key 无效或未充值 | 检查 Key 是否复制完整、是否已充值 |
| `429` / `Rate limit` | 请求太频繁 | 等几秒再试；按量付费额度够用 |
| `Connection ... failed` | 网络不通 | 检查能否访问 api.deepseek.com |

## 换用其他兼容 API（可选）

脚本支持通过环境变量替换端点（OpenAI 兼容格式），例如：

```bash
export LLM_API_URL=https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions
export LLM_MODEL=qwen3.6-flash
export DEEPSEEK_API_KEY=你的阿里百炼Key
python3 chat.py
```

默认模型为 `deepseek-v4-flash`（DeepSeek 官方 API）。模型名可能随官方调整，以 https://api-docs.deepseek.com 为准。

## 这个 demo 说明了什么

跑完之后请带着一个问题离开：**这个模型能「做事」吗？**
它只是把「你输入的文本 + 它记得的历史」拼在一起，预测下一段文本——查天气、订机票、操作文件，它全都做不到。这就是下一篇要解决的问题：怎么让一个只会说话的模型开始「干活」。
