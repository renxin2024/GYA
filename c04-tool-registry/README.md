# C04 演示：工具注册表与 ToolResponse

本地确定性实验，验证工具缺失、工具下线、参数错误、超时、其他执行错误、正常调用与幂等查询；另覆盖一次“候选 schema 缺少 `idempotency_key`”的更新回归。

它不调用 LLM、订单或支付系统，也不需要 API Key。`RefundDomain` 仅用于观察 Runtime 与领域 handler 的职责边界，不能替代生产级持久化和对账。

## 运行

Python 3.10+，零第三方依赖：

```bash
python3 registry.py
python3 -m unittest test_registry.py
```

Java 21 + Gradle：

```bash
gradle run
```

Java 版看到 `ALL_TESTS_PASSED` 即通过；它与 Python 版跑的是同一组断言。

## 完整输出记录

主线 Trace（`python3 registry.py`）——`refund_order` 已成功但响应超时，Runtime 先查幂等状态、发现 `SUCCEEDED` 后回放结果，不再二次退款：

```text
refund_order response=EXECUTION_ERROR
idempotency_status=SUCCEEDED
runtime_action=REPLAY_SUCCESS
final=SUCCESS
refund_order handler_execution_count=1
```

最后一行是整条链路的关键证据：Runtime 经历了「超时 → 查状态 → 回放」，真正执行退款的 handler 只跑了一次。

`test_registry.py` 的 7 项测试覆盖：未知工具、工具下线、参数错误、其他执行失败、坏更新保留健康旧版、超时已成功回放、超时未执行重试一次。

## 目录

- `registry.py` / `test_registry.py`：配套实现（Python）
- `legacy/`：早期版本（`registry_learning.py`），与文章不对应，仅供追溯

Java 对照实现见 [GYA-Java 的 c04 目录](https://github.com/renxin2024/GYA-Java/tree/main/c04-tool-registry)。
