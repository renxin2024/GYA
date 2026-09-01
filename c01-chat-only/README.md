# C01 演示：一次最小调用，看清职责边界

一个只做一件事的最小客户端：把「一次调用里谁发了什么、谁收到了什么」打印成 Trace。它不会自动查天气、也不会调用工具——这正是 C01 要你看清的边界。

## 前置环境

| 项 | 要求 |
|----|------|
| Python | 3.9+（`python3 --version` 查看） |
| 依赖 | 无（只用标准库） |
| API Key | DeepSeek 官方 Key（仅真实调用需要，`--dry-run` 不需要） |

Java 等价实现见 **GYA-Java** 仓库的 `c01-chat-only/`。

## 运行

```bash
# 不联网：看 Runtime 会组装出什么样的请求
python3 main.py --dry-run "上海今天天气怎么样？"

# 注入一条 system 级运行时提示（注意看 request.prepared 里 system 的位置与脱敏）
RUNTIME_CONTEXT="只回答可以从请求证明的事实" python3 main.py --dry-run "上海今天天气怎么样？"

# 真实调用
export DEEPSEEK_API_KEY=sk-你的key
python3 main.py "上海今天天气怎么样？"
```

## 预期输出

空上下文 dry-run：

```json
{"event":"context.skipped","owner":"client_runtime","source":"env:RUNTIME_CONTEXT","reason":"empty_optional_context"}
{"event":"request.prepared","owner":"client_runtime","method":"POST","url":"https://api.deepseek.com/chat/completions","headers":{"Content-Type":"application/json","Authorization":"Bearer <redacted>"},"body":{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"上海今天天气怎么样？"}],"stream":false}}
{"event":"run.finished","owner":"client_runtime","outcome":"dry_run_no_network"}
```

非空 `RUNTIME_CONTEXT` 时，第一条 Trace 变为 `context.prepared`（含 `role=system`、字节数与 SHA-256），`request.prepared` 的 `messages` 变成 `system → user`，且 system 原文显示为 `<redacted>`。

## 失败排查

- `ModuleNotFoundError` / Python 版本过低 → 用 `python3 --version` 确认 ≥ 3.9。
- 真实调用返回认证错误 → 检查 `DEEPSEEK_API_KEY`（或 `LLM_API_KEY`）是否已 `export`、是否复制多/少了字符。
- 真实调用网络超时/连不上 → 换网络或确认本机未被墙/代理；`--dry-run` 不联网，可先单独验证代码本身。
