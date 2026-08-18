# GYA

《我了解的大模型和 Agent》系列文章的配套代码仓库。

## 这个仓库是什么

本仓库是博客系列 **《我了解的大模型和 Agent》** 的可运行代码集合。系列从「模型只会说话」讲起，一步步拆解 Agent 能力的每次跃迁——Function Calling、Agent 循环、MCP 协议、Skill 系统、多 Agent 协作——每篇文章都配一个能直接跑起来的最小演示。

> 系列文章发布在 https://www.renxinblog.cn （搜索「Agent」）
> 文章正文在文章站点，能跑的代码在这里。

## 目录导航

| 目录 | 对应文章 | 内容 | 状态 |
|------|---------|------|------|
| `c01-chat-only/` | 01 只会说话的模型 | 40 行命令行聊天程序，体验"文本补全器" | ✅ 可运行 |
| `c02-function-calling/` | 02 Function Calling 第一性原理 | （规划中） | ⏳ |
| `c03-model-training/` | 03 模型怎么被训出来的 | （规划中） | ⏳ |
| `c04-tool-registry/` | 04 工具注册表与 ToolResponse | （规划中） | ⏳ |
| `c05-react-agent/` | 05 手写 ReAct Agent | （规划中） | ⏳ |
| ... | ... | ... | ... |

## 运行前置

- Python 3.10+
- 各 demo 的 API Key 要求见对应目录 README（多数用 DeepSeek 官方 API，按量付费，注册 2 分钟）

## 贡献与反馈

本仓库随系列文章持续更新。发现 demo 跑不通或有更好的写法，欢迎提 issue / PR。

## 许可

MIT