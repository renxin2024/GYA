# C07 演示：四层记忆——工作、情节、语义、程序

一个演示「上下文窗口 ≠ 记忆」的最小程序：四层记忆模型 + SQLite 持久化 + 真实 Embedding 语义检索，以及「记忆如何进入本轮上下文」的完整闭环。

## 演示内容

1. **情节记忆（Episodic）**：事实「预设写入」SQLite（演示不包含「从对话自动提取关键事实」那道工序）→ 模拟进程重启 → 读回，事实不丢；再用 `by_subject` / `by_session` / `search` 三种 SQL 查询演示「情节记忆怎么召回」
2. **语义记忆（Semantic）**：bge-m3 真实 Embedding 向量化 → Qdrant 检索 → 跨会话召回偏好；**同义改写（「爱喝」vs「喜欢喝」）也能命中**
3. **完整闭环**：保存记忆 → 新会话提问 → 检索候选 → 组装上下文 → 调用模型，对照三种情况：
   - **有记忆**：检索命中偏好，模型能回答，答案可追溯到命中条目；
   - **无记忆**：不给检索结果，模型不能编造用户信息；
   - **无命中**：检索不到相关信息，模型应承认信息不足。
4. **程序记忆（Procedural）**：只点一句「记怎么做、而非记了什么事实」，钩第九话 Skill

## 四层记忆（按「区分依据」划分；存储介质是实现选择）

| 类型 | 区分依据 | 本篇用的实现 |
|---|---|---|
| 工作记忆 Working | 当前决策正在使用的信息 | 内存 messages |
| 情节记忆 Episodic | 具体经历及其发生背景 | SQLite 事实表 |
| 语义记忆 Semantic | 提炼后的事实、知识或偏好 | Qdrant 向量检索 |
| 程序记忆 Procedural | 完成任务的方法或行为规则 | 代码/Skill（钩 C09） |

> 存储介质不是记忆类型的定义：情节记忆同样能做向量检索，语义记忆也能走 SQL 精确查询。CoALA（arXiv 2309.02427）明确讨论了「从情节记忆中检索经历来支持推理」。

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
[1] 情节记忆：关键事实落 SQLite，重启读回 + SQL 召回
重启后读回的事实：
  - 用户名: 张三
  - 偏好: 最近在戒咖啡，想少喝一点
  - 职业: Java 后端工程师

（情节记忆怎么召回：SQL 精确查询，不靠全量读回）
  按 subject 精确查「偏好」→ 命中 1 条：
    - 最近在戒咖啡，想少喝一点
  按 session 查「session-A」→ 命中 3 条（这场对话发生过的所有事）
  按关键词模糊查「咖啡」→ 命中 1 条：
    - 偏好: 最近在戒咖啡，想少喝一点

[2] 语义记忆：bge-m3 + Qdrant，跨会话召回（含同义改写）
  问「用户喝咖啡吗？」→ 命中 [用户最近在戒咖啡，想少喝一点]  score=0.753
  问「用户想戒掉什么？」→ 命中 [用户最近在戒咖啡，想少喝一点]  score=0.783
  问「用户职业是什么？」→ 命中 [用户职业是 Java 后端工程师，擅长并发编程]  score=0.704

[3] 完整闭环：检索结果 → 组装上下文 → 模型回答
  问：我最近在戒咖啡，聚餐时该注意什么？
  检索命中 1 条，组装进 system 消息：
    - [用户最近在戒咖啡，想少喝一点]（相似度 0.753）
  模型（有记忆）: 你最近在戒咖啡，聚餐时留意含咖啡因的饮品。
  模型（无记忆）: 我无法判断你的饮食偏好。
  模型（无命中）: 我没有关于你去过的地方的信息。
```

注意第 2 段前两行：问「**喝咖啡吗**」和「**想戒掉什么**」字面几乎没有重叠，却都命中了同一条「戒咖啡」记忆——这是真实 Embedding 的价值：同义/相关表达投影到相近向量。旧版纯 bigram 分词匹配不到这种改写。

## 它证明的事

1. **上下文窗口 ≠ 记忆**：模型单次调用不会自动记住历史，跨会话的信息需要由应用这层保存、检索、再喂回
2. **情节记忆 = 经历及其背景**：把关键事实落盘（SQLite 只是本篇选的介质），能活过重启
3. **语义记忆 = 检索**：不检索的记忆等于不存在——真实 Embedding + Qdrant 让 Agent 跨会话「想起」用户是谁
4. **记忆要进入上下文才生效**：检索命中只是第一步，把命中条目组装进消息、再让模型据此回答，才构成完整闭环
5. **无 Embedding 服务时的降级**：离线 TF-IDF 兜底只证明「检索」机制本身，不冒充真实 Embedding 的同义改写能力

## 常见坑

1. **Q: Embedding/Qdrant 没起，跑不通？**
   A: `memory_demo.py` 的语义部分会降级到离线 TF-IDF（打印 ⚠️ 提示），且降级覆盖「写入 + 检索」全程，不只是初始化。真实 Embedding 需要 Ollama bge-m3 服务在线（Hermes 的 `embedding` 容器）。
2. **Q: Qdrant 写入报 400「not a valid point ID」？**
   A: Qdrant 的 point id 只接受无符号整数或 UUID，不接受数字字符串。本 demo 已用整数 id。
3. **Q: Java 版跑报 SQLITE_IOERR_DELETE？**
   A: 受限沙箱环境的 seatbelt 会拦 SQLite 默认 journal 的 unlink 调用。**默认不关闭 journal**（保留崩溃安全）；只有在受限环境里，才通过环境变量 `MEMORY_SQLITE_UNSAFE_NO_JOURNAL=1` 显式关闭，仅限一次性实验。正常终端切勿开启。
4. **Q: 为什么不用更「工业」的向量库/框架？**
   A: 演示目的是理解「记忆分层 + 检索」这个机制本身。生产可以用任意向量库，原理一致。

## 文档

- 文章正文在博客站点（`renxinblog.cn` 的 GYA 系列）。
- 配套 Java 等价实现见 [GYA-Java 仓库](https://github.com/renxin2024/GYA-Java/tree/main/c07-memory)（Java 21 + Gradle + sqlite-jdbc，关键 Trace 与 Python 版一致）。
- 语义检索的 Embedding 模型：BAAI `bge-m3`（1024 维，多语言，Ollama 部署）。
