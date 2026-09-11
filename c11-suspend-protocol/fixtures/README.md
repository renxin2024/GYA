# fixtures 说明：教学合成资料

本目录的 `material_1` / `material_2` 是**教学合成数据**，只承担控制流实验，不是权威事实来源。

## 设计意图

- `material_1`：首次 `read_material` 只返回 `[partial]` 内容 + 一条 `follow_up` 线索，指向 `material_2`。
- `material_2`：补齐「审批边界与运行时准入」的结论。

这条 `follow_up` 线索**只能通过 `read_material` 的工具结果获得**，不写进模型提示词——这是「动态资料暴露决策差异」的关键：它逼着控制器根据新观察做下一步，而不是靠预知。

## 三种等待信号来源如何走到这条线索

三种来源拿到的是**同一份资料清单**（知道有哪些资料，不知道读取顺序），差别只在「谁决定下一步」：

| 来源 | 响应方式 |
|---|---|
| ReAct | 第 2 步读到 `follow_up` → 第 3 步才读 `material_2`（模型看着观察决定） |
| Plan-and-Execute | 计划里就写了读 `material_2` 这一步（计划约束） |
| Workflow | 真条件分支：代码先检查工具结果里有没有 `follow_up` 线索，有才读 `material_2` |

> 旧版把「先读 material_1，再读 material_2」直接写进 Planner 提示词，等于提前把路径交给了 Planner，
> 让那场比较对 ReAct 不公平；本版已删除该硬编码。旧版 Workflow 也无条件读 `material_2` 却把这次调用
> 标成 `node_read_followup`，本版改成真分支：关闭线索（`--no-follow-up`）时 `branch_taken=false`，
> 不再读第二份。


## 边界声明

合成资料的内容是「关于控制模式的简化说明」，**不是** ReAct/Plan-and-Execute/Workflow 的权威定义或事实依据。正文引用真实来源时使用论文与官方文档，不使用本目录的合成文本。

实际的资料内容硬编码在 `python/state.py` 的 `MATERIALS` 字典与 `java/.../Main.java` 的 `MATERIALS` map 里，本目录仅作说明。
