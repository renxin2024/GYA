# C07 演示：四层记忆——工作、情节、语义、程序

一个演示「上下文窗口 ≠ 记忆」的最小程序：四层记忆模型 + SQLite 持久化 + 真实 Embedding 语义检索。

## 演示内容

1. **情节记忆（Episodic）**：会话中提取「我叫张三 / 我爱喝茶 / 我是 Java 后端」→ 存 SQLite → 模拟进程重启 → 读回，事实不丢
2. **语义记忆（Semantic）**：bge-m3 真实 Embedding 向量化 → Qdrant 检索 → 跨会话召回偏好；**同义改写（「爱喝」vs「喜欢喝」）也能命中**
3. **无记忆对照**：同样的问题没有任何上下文时，模型明确回答「我不知道你是谁」
4. **程序记忆（Procedural）**：只点一句「事实会过期，方法可复用」，钩第九话 Skill

## 四层记忆

| 层 | 是什么 | 存哪 | 怎么失效 |
|---|---|---|---|
| 工作记忆 Working | 窗口内的完整对话 | 内存 messages | 窗口满、进程重启 |
| 情节记忆 Episodic | 会话内提取的关键事实 | SQLite | 需主动写、主动读 |
| 语义记忆 Semantic | 跨会话的偏好/知识 | Qdrant 向量检索 | 不检索等于不存在 |
| 程序记忆 Procedural | 怎么做事的方法/流程 | 代码/Skill（钩 C09） | 本篇不展开 |

## 前置环境

| 项 | 要求 |
|----|------|
| Python | 3.10+（`python3 --version` 查看） |
| Embedding | Ollama `bge-m3`（经 hermes-gateway stream 代理，宿主机 `127.0.0.1:11434`） |
| Qdrant | 向量库 `127.0.0.1:6333`（需 `QDRANT_API_KEY`） |
| LLM（可选） | DeepSeek 官方 Key，只做「无记忆 vs 有记忆」对照 |
| 依赖 | 仅标准库（urllib / sqlite3 / math），无需 pip install |

## 运行

```bash
export QDRANT_API_KEY=你的key          # Hermes .env 里有
export DEEPSEEK_API_KEY=sk-你的key      # LLM 对照用，可选

# 离线回归（不依赖 Embedding/Qdrant/LLM）
python3 -m unittest test_memory -v

# 完整演示
python3 memory_demo.py
```

## 预期输出（关键部分）

```
[1] 情节记忆：关键事实落 SQLite，重启读回
重启后读回的事实：
  - 用户名: 张三
  - 偏好: 喝茶，尤其是龙井
  - 职业: Java 后端工程师

[2] 语义记忆：bge-m3 + Qdrant，跨会话召回（含同义改写）
  问「用户喜欢喝什么？」→ 命中 [用户喜欢喝茶，尤其是龙井]  score=0.753
  问「用户爱喝什么饮料？」→ 命中 [用户喜欢喝茶，尤其是龙井]  score=0.705
  问「用户职业是什么？」→ 命中 [用户职业是 Java 后端工程师，擅长并发编程]  score=0.704

[3] 无记忆对照：模型没有上下文时，答不上'我是谁'
  模型: 我不知道你是谁，也不知道你叫什么名字。
```

注意第 2 段第二行：问「**爱喝**什么饮料」命中的是「**喜欢**喝茶」——这是真实 Embedding 的价值：同义改写投影到相近向量。旧版纯 bigram 分词匹配不到这种改写。

## 它证明的事

1. **上下文窗口 ≠ 记忆**：模型本身不「记得」，全靠我们每次把历史塞进 prompt。塞不下的、进程重启就丢的，就是「遗忘」
2. **情节记忆 = 显式提取 + 落盘**：把关键事实提取成结构化条目存 SQLite，比全量历史更省 token，且能活过重启
3. **语义记忆 = 检索**：不检索的记忆等于不存在——真实 Embedding + Qdrant 让 Agent 跨会话「想起」用户是谁
4. **无 Embedding 服务时的降级**：离线 TF-IDF 兜底只证明「检索」机制本身，不冒充真实 Embedding 的同义改写能力

## 常见坑

1. **Q: Embedding/Qdrant 没起，跑不通？**
   A: `memory_demo.py` 的语义部分会自动降级到离线 TF-IDF（打印 ⚠️ 提示）。真实 Embedding 需要 Ollama bge-m3 服务在线（Hermes 的 `embedding` 容器）。
2. **Q: Qdrant 写入报 400「not a valid point ID」？**
   A: Qdrant 的 point id 只接受无符号整数或 UUID，不接受数字字符串。本 demo 已用整数 id。
3. **Q: Java 版跑报 SQLITE_IOERR_DELETE？**
   A: 受限沙箱环境的 seatbelt 会拦 SQLite 默认 journal 的 unlink 调用。Java 版 `newDb()` 里已用 `PRAGMA journal_mode=OFF` 绕过；正常本地终端可去掉这两行恢复崩溃安全。
4. **Q: 为什么不用更「工业」的向量库/框架？**
   A: 演示目的是理解「记忆分层 + 检索」这个机制本身。生产可以用任意向量库，原理一致。

## 文档

- 文章正文在博客站点（`renxinblog.cn` 的 GYA 系列）。
- 配套 Java 等价实现见 [GYA-Java 仓库](https://github.com/renxin2024/GYA-Java/tree/main/c07-memory)（Java 21 + Gradle + sqlite-jdbc，关键 Trace 与 Python 版一致）。
- 语义检索的 Embedding 模型：BAAI `bge-m3`（1024 维，多语言，Ollama 部署）。
