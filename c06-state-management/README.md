# C06 崩溃恢复 + 幂等 demo

把 C05 只在内存里的循环，升级成「断了能接着跑、做过的事不重做」的版本：进度落盘、崩溃后能恢复、有副作用的步骤能幂等。

## 文件

- `state_management.py`：核心实现（零第三方依赖）
  - `AgentState`：显式状态（task / messages / trace / next_step / done_steps）
  - `CheckpointStore`：JSON 落盘
  - `DurableRuntime`：checkpoint + 恢复 + 副作用幂等
  - `Inventory`：带副作用记录的本地夹具（扣库存 / 发通知）
  - `ScriptedModel`：离线脚本模型（脚本耗尽 = 进程崩溃）
- `test_state_management.py`：7 项离线回归测试（checkpoint 往返与原子写、正常跑、崩溃前未落盘、崩溃后恢复、重复恢复不重启、幂等重放）

## 另见

`langgraph-compare/`：一个**独立的对照 demo**——同一个任务分别用手写状态机与 LangGraph StateGraph 实现，演示「图管流程、LLM 管内容」（需要 DeepSeek Key）。它与本篇的崩溃恢复主题无关，见该目录的 README。

## 运行

```bash
# 离线回归，不需要 Key
python3 -m unittest test_state_management.py -v

# 演示两条路径（正常跑完 + 崩溃恢复）
python3 state_management.py
```

## 核心验证点

| 场景 | 证明什么 |
| --- | --- |
| 正常跑完 | 查库存 → 扣库存 → 发通知，两个副作用各执行一次 |
| 崩溃恢复 | 扣库存后进程被杀，恢复后接着发通知，`deduct_count=1`（不重复扣） |
| 幂等重放 | 即使重放扣库存，`Inventory` 返回 `ALREADY_DONE`，库存只扣一次 |

## 与 C05 的演进关系

C05 的循环把 `messages` 当成了「历史 + 进度」的混合容器，进度藏内存里，进程一死就归零。
C06 把进度拆成清晰字段，`messages` 只保留「模型需要看到的对话」，进度交给 `next_step` /
`done_steps`，因此可以落盘、恢复、幂等。

## 完整输出记录

文章第五节引用的两次崩溃恢复实验（`python3 state_management.py`）：

### 实验一：扣库存成功、checkpoint 尚未写时进程被杀

```
checkpoint 不存在（没来得及写）
重新 deduct -> ALREADY_DONE
库存仍 = 9（只扣了一次）
```

### 实验二：checkpoint 已保存后恢复，完成剩余操作

```
--- (进程崩溃，全新进程恢复) ---
recovered_from_checkpoint
step tool=notify_shipped   observation=NOTIFIED
status=COMPLETED
deduct_count=1  notify_count=1
```

实验一里 checkpoint 是空的，靠 SQLite 的幂等记录 + 唯一约束挡住了重复扣库存；
实验二里 checkpoint 已落盘，恢复后模型读到「扣库存已经做过了」，补充执行了漏掉的发通知。
两者合起来说明：**业务事实才是「不重复」的最终兜底，checkpoint 只负责让决策上下文能接上。**
