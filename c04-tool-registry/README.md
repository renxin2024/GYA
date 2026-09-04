# C04 实验：工具注册表与 ToolResponse

本地确定性实验，验证工具缺失、工具下线、参数错误、超时、其他执行错误、正常调用与幂等查询；另覆盖一次“候选 schema 缺少 `idempotency_key`”的更新回归。

它不调用 LLM、订单或支付系统，也不需要 API Key。`RefundDomain` 仅用于观察 Runtime 与领域 handler 的职责边界，不能替代生产级持久化和对账。

## 运行

环境：Python 3.10+，无第三方依赖。

```bash
python3 registry_learning.py
python3 -m unittest test_registry_learning.py
```

通过标准：7 项测试全部通过；示例 Trace 中包含 `REPLAY_SUCCESS`，并打印 `refund_order handler_execution_count=1`。这证明超时后查询到已成功时，Runtime 回放结果而不是再次执行退款。

Java 21 对照实现见 [GYA-Java 的 C04 目录](https://github.com/renxin2024/GYA-Java/tree/main/c04-tool-registry)。
