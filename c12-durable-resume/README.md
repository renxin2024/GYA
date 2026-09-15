# C12 可恢复审批：Run 停了之后怎样安全地继续

上一话的结尾留了一个不好绕过去的问题：三种模式都能在当前进程里让 Run 停下来，进入等待用户确认。但一退出进程，内存里那条「等待审批」也跟着没了。第二天用户回来说「确认」，你凭什么找到对应的那份纲领、对应到哪个动作、恢复到哪个进度？

结论落在代码里：可恢复的 Human-in-the-Loop 不只是「把状态存进 SQLite」。系统要把审批绑定到一个不可变的待执行动作版本，恢复时同时校验「你批准的是不是这个动作」和「批准之后动作有没有被改过」，执行时靠业务幂等键不重复做事——缺一条都恢复不了。

> 本目录是 Python 实现（博客正文主语言）。Java 等价实现在 [GYA-Java 仓库](https://github.com/renxin2024/GYA-Java/tree/main/c12-durable-resume) 的 `c12-durable-resume` 目录。

## 目录入口

```
c12-durable-resume/
├── README.md       # 本文件
└── python/
    ├── main.py        # Store：checkpoint + 审批绑定 + 幂等恢复 + Trace
    └── test_main.py   # unittest 测试（10 项）
```

Python 3.11+ 只使用标准库 SQLite，无第三方依赖、无需 API Key。`start` 会确定性地构造一个固定的 `write_draft` proposal，代替上游 LLM 输出。

## 运行

```bash
cd python
PYTHONPYCACHEPREFIX=/private/tmp/c12-pycache python3 -B -m unittest -v   # 10 项测试

python3 main.py --db /tmp/c12.db --output /tmp/c12-draft.txt start run-1
python3 main.py --db /tmp/c12.db --output /tmp/c12-draft.txt show-trace run-1
# 从 JSON 输出复制 proposal_hash。
python3 main.py --db /tmp/c12.db --output /tmp/c12-draft.txt approve run-1 --proposal-hash '<hash>'
python3 main.py --db /tmp/c12.db --output /tmp/c12-draft.txt resume run-1
python3 main.py --db /tmp/c12.db --output /tmp/c12-draft.txt show-trace run-1
```

## 验收语义

- proposal 的 hash 覆盖 `action + args + output` 三者。固定 proposal（output 取 `/tmp/c12-draft.txt`）的 hash 是 `2bba1bb36ae552812b4b9e0d730249a3447adfc3ed100e0f4d92e3a8c28e7573`（Python / Java 两端一致）。
- 审批同时保存 `approval_request_id` 和 `approval_hash`；恢复时既比较当前 request ID，也重新计算 action/args/output 的 hash，并显式比对本次传入的 output 是否等于批准时冻结的 output。批准后替换 pending request、proposal 或 output 都会被拒绝。
- 正常完成后重复 `resume` 返回 `already_completed`，Trace 留 `action_replayed`。
- 测试在「文件已创建、COMPLETED 尚未写回」之间注入崩溃；重试发现相同幂等键对应的文件内容已存在时返回 `recovered`，不重写文件。
- 同一路径已存在但内容不同，恢复返回 `output_conflict`，不覆盖原文件。

## 已知边界

本 demo 只证明这个固定本地文件动作的幂等策略。SQLite 事务不能覆盖数据库之外的文件、邮件或支付；生产系统仍需业务幂等键、outbox/inbox 或目标系统提供的去重能力（这些属设计候选，本文未验证）。

## 挂起时返回的形态

Runtime 挂起当前 Run 时，`handle()` 返回的对象长这样（文章第一节引用的就是这三个字段）：

```text
brief_id="brief-1"
status="WAITING_FOR_USER"
waiting_reason="unsafe_action:write_brief"
```

单进程内 `brief_id` 还在内存里，接着调 `handle("confirm", "brief-1")` 就能继续；但进程一退出，这三个字段全没了——可恢复的前提是它们已经落盘。
