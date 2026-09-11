# C11 暂停协议：模型只提决定，Runtime 才让 Run 停下来

同一个技术文章创作任务跑三种等待信号来源（ReAct / Plan-and-Execute / Workflow），
看一件事：**模型说了「请用户确认」以后，程序为什么真的会停下来？**

结论落在代码里：模型不能暂停程序。模型只能提出候选决定；
`Runtime` 负责解析它、校验当前状态允不允许它、执行状态迁移，
再告诉调度器「继续、挂起、完成还是失败」。

> 本目录是 Python 实现（博客正文主语言）。Java 等价实现在 [GYA-Java 仓库](https://github.com/renxin2024/GYA-Java/tree/main/c11-suspend-protocol) 的 `c11-suspend-protocol` 目录。

## 目录入口

```
c11-suspend-protocol/
├── README.md              # 本文件
├── fixtures/              # 教学合成资料说明（不是权威事实来源）
├── traces/                # 脱敏运行记录
│   ├── offline-python-*.log   # Python 离线夹具（正确版 / 缺陷版 / 关闭线索分支）
│   ├── offline-java-*.log     # Java 离线夹具（正确版 / 缺陷版），与 Python 逐字段一致
│   ├── live-run-1..6.log      # 真实模型（deepseek-v4-flash）6 次
│   └── superseded/            # 旧设计（三模式并列）的历史记录，仅供对照
└── python/                # Python 实现
    ├── protocol.py        # DecisionType / RunStatus / ControlDecision / PendingRequest / Transition / TraceEvent
    ├── state.py           # RunState（含等待快照）/ VirtualStore / 教学资料
    ├── tools.py           # 工具 + ActionGateway（动作准入）
    ├── runtime.py         # Runtime：解析 + 前置条件校验 + 状态迁移（唯一迁移点）
    ├── controllers.py     # 三种控制器：只提出决定，改不了状态
    ├── scheduler.py       # 带 Runtime 的循环 + 没有 Runtime 的缺陷版循环
    ├── plan_validator.py  # 计划校验器（只检查结构）
    ├── llm.py             # LlmClient（真实调用 + 离线夹具）
    ├── main.py            # CLI 入口
    └── test_suspend_protocol.py  # 离线测试（20 项）
```

## 四层职责

| 层次 | 职责 | 代码落点 |
|---|---|---|
| 模型 | 根据上下文提出动作、结束或请求用户输入 | `controllers.py` 的提示词与 `llm.py` |
| Runtime | 解析模型输出，校验状态前置条件，决定状态迁移 | `runtime.py` |
| Scheduler | 按迁移结果决定继续循环还是退出当前 Run | `scheduler.py` |
| UI / Continuation | 展示问题、接收用户输入、创建下一次执行 | 本 demo 只到「返回调用方」为止（C12） |

`controller.decide()` 只提出决定；只有 `runtime.handle()` 拥有状态迁移权。

## 三种来源的一句话区别

| 来源 | 等待信号从哪来 | 它**没有**做什么 |
|---|---|---|
| ReAct | 模型在观察后自己提出 `REQUEST_USER_INPUT` | 不改变 Run 状态，也不停止循环 |
| Plan-and-Execute | 计划里的一步，执行器照原样交给 Runtime | 计划文本本身没有暂停能力 |
| Workflow | 代码里的固定节点，到达即提出 | 不决定状态迁移，迁移仍由 Runtime 做 |

三者都汇聚到同一个入口：`ControlDecision → Runtime → RunStatus → Scheduler`。

## 前置环境

| 项 | 要求 |
|---|---|
| Python | 3.10+（标准库，无 pip 依赖） |
| API Key | 仅 `--live` 需要（`LLM_API_URL` + `LLM_MODEL` + `LLM_API_KEY` 或 `DEEPSEEK_API_KEY`） |

## 运行

### 离线（不需要 API Key）

```bash
cd python
python3 -m unittest test_suspend_protocol -v   # 20 项控制流契约测试
python3 main.py                               # 三种来源正常跑：全部停在同一边界
python3 main.py --naive                       # 缺陷版：没有 Runtime 的循环
python3 main.py --no-follow-up                # 关闭 material_1 的线索，验证 Workflow 是真条件分支
```

### 真实模型

```bash
cd python
export LLM_API_URL=https://api.deepseek.com/chat/completions
export LLM_MODEL=deepseek-v4-flash
export LLM_API_KEY=...                        # 或 DEEPSEEK_API_KEY
python3 main.py --live
```

> `deepseek-v4-flash` 是推理模型：默认会把大量 token 花在 `reasoning_content` 上。
> `llm.py` 通过 `thinking: {"type": "disabled"}`（DeepSeek V4 官方参数）+ `max_tokens=4096`
> + `response_format=json_object` 让它直接输出可解析的 JSON 决定。
> `thinking` 不是所有 OpenAI 兼容接口的通用参数，换服务前先查文档。

## 它证明的事

1. **模型输出只是数据，不是控制流。** 自然语言「请用户确认」在 `Runtime.parse()` 处就会失败——它不是机器可识别的等待信号。
2. **`waiting=true` 不等于循环已经停止。** 缺陷版把等待记成一个布尔标记后继续跑：ReAct 那一路一直转到预算耗尽；Plan-and-Execute 那一路甚至跨过等待点去尝试 `write_draft`，直到被 Gateway 拦下。
3. **Gateway 拦截不等于 Run 暂停。** Gateway 回答「这个动作能不能执行」，Runtime 回答「当前 Run 要不要继续」。被拦住时状态仍是 `RUNNING`，也没有 pending request。
4. **非法状态下的等待信号会被拒绝。** 还没有 `create_brief` 就提出等待、或者等待不带问题，都会被拒绝（前者让 Run 明确失败，不留下 pending）。
5. **「停下」是可验证的，不是自述的。** 判据 `is_run_suspended()` 要求四件事同时成立：状态是 `WAITING_FOR_USER`、有 pending request、等待后模型调用增量为 0、工具尝试增量为 0。缺陷版会在这条判据上失败——这正是测试抓住它的方式。
6. **解析失败不留活路。** Runtime 无法解释的输出不会「当成正常动作混过去」，而是让 Run 以明确失败结束（真实运行里真的发生了，见下）。
7. **三种来源只是信号产生方式不同。** 它们的等待事件序列完全一致：`signal_received → runtime_validated → state_transition → pending_recorded → run_exited`。

## 真实模型观察（deepseek-v4-flash，6 次运行）

这一节只报告实际运行结果，不上升为普遍结论。

**Plan-and-Execute 6/6、Workflow 6/6 走到 `WAITING_FOR_USER`**，`model_calls_after_wait` 与
`tool_calls_after_wait` 全为 0。其中 Planner 那句等待文案是模型自己写的
（「以上是根据本地资料整理的纲领，请确认是否满意？」），但**把它解释成状态迁移的是 Runtime**。

**ReAct 6/6 都没有产出可被 Runtime 解释的等待决定**，分成两种结束方式：

| 结果 | 次数 | 现象 |
|---|---|---|
| `budget_exhausted` | 3 | 预算内反复 `read_material`，一直没有提出等待 |
| `parse_failed` | 3 | 模型多包了一层信封，Runtime 拒绝猜测 |

`parse_failed` 那三次的实际输出：

```json
{"type": "json_object", "content": {"type": "EXECUTE_TOOL", "action": "read_material", "args": {"material_id": "material_2"}}}
```

模型把决定放进了 `content`，外层 `type` 变成了 `json_object`。Runtime 只看顶层 `type`，
认不出这个类型就判失败——它不会去猜「里面那个是不是真决定」。这条比任何设想都更适合说明主论点：
**「模型表达了意图」与「Runtime 承认这是一个决定」是两件事。**

同样代码、同样提示词、`temperature=0`，两次批次给出了不同的结束方式（一次批次 2 次解析失败 + 1 次预算耗尽，
另一次 1 次解析失败 + 2 次预算耗尽）。这说明该服务端的输出并非严格可复现，因此上面的数字只描述这 6 次运行。

> 离线 Fixture 用来验证 `Runtime` 状态迁移、调度器停止、Gateway 拦截与 Trace 契约；
> 它**不能**替代真实模型行为证据，真实运行也不能替代离线回归。

## 教学数据声明

`fixtures/` 下的资料是**教学合成数据**，只承担控制流实验，不是权威事实来源。正文不会把它当事实依据。

## 已知边界（C11 只做到这里）

本 demo 不实现、也不声称已经实现：数据库持久化；进程重启后恢复；多实例恢复；
审批结果与具体动作绑定；重复审批幂等；超时与取消；恢复后避免重复副作用。
这些属于 C12：当前 Run 停下来之后，怎样找到原进度并安全地继续。

真实模型实验只在 Python 侧执行（Java 侧只有离线夹具），两种语言之间这一点不对称，
见 [GYA-Java](https://github.com/renxin2024/GYA-Java/tree/main/c11-suspend-protocol) 的说明。

## 常见坑

1. **`--live` 报空 content**：先区分是响应结构、截断、接口错误还是格式解析问题。推理模型的 `max_tokens` 过低时 `content` 会被截断为空（`finish_reason=length`）；修复是「增大 max_tokens + 按服务方文档关掉 reasoning」，不是「关闭思考模式」这个万能口号。
2. **`parse_failed` 不一定是模型乱答**：也可能是多包了一层信封（见上）。Trace 的 `result` 字段会带上被拒绝的原始输出，先看它再改提示词。
3. **离线测试跑不通**：`state.py` / `tools.py` / `llm.py` 都不在模块顶部 import 真实模型依赖，离线测试无需网络或 Key；若报 import 错误，确认在 `python/` 目录下运行。
