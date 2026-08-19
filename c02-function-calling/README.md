# C02 演示：Function Calling 第一性原理

一个演示「模型根本没有真正调用工具——它只是输出了一个 JSON，真正执行的是你的代码」的最小程序。

支持 **Python 3.10+** 与 **Java 21** 两个版本，任选其一运行。

## 版本总览

| 版本 | 位置 | 环境 | 运行方式 |
|------|------|------|---------|
| Python（教程正文用） | `main.py` | Python 3.10+，零依赖 | `python3 main.py` |
| Java 21 | `java/Main.java` | JDK 21，零依赖（单文件运行） | `java Main.java` |

（Java 版用 JDK 自带 `java.net.http.HttpClient` + 极简正则解析 JSON，刻意保持零依赖，与 Python 版「无需 pip install」对等；生产环境请换 Jackson/Gson。）

## 前言：两种语言的核心逻辑完全一致

无论 Python 还是 Java，演示的都是同一个闭环、同一段流程：

```
发请求（带 tools）→ 模型输出 tool_calls JSON → 调用方解析 → 调用方执行 get_weather()
→ 把结果回喂（role=tool）→ 模型基于结果生成最终回答
```

模型只会「说」它想调什么工具；真正「做」事的永远是调用方代码。

## 获取 API Key（约 2 分钟，两种版本通用）

1. 打开 https://platform.deepseek.com 注册/登录
2. 左侧「API Keys」→「创建 API Key」，复制 `sk-...`
3. （按量付费需先充值：控制台「充值」最低 10 元）

## 运行 Python 版

```bash
export DEEPSEEK_API_KEY=sk-你的key
python3 main.py
```

## 运行 Java 版（JDK 21）

```bash
export DEEPSEEK_API_KEY=sk-你的key
cd java
java Main.java        # JDK 11+ 直接运行单文件，无需编译/打包
```

> 需要 JDK 21（LTS）。你的环境没装的话：
> - macOS: `brew install openjdk@21`
> - Ubuntu/Debian: `sudo apt install openjdk-21-jdk-headless`
> - Windows: 从 [Adoptium](https://adoptium.net) 下载 21 安装包
> - 验证：`java -version` 显示 `21.0.x`

## 预期输出（两版一致，措辞可能略有差异）

```
模型: deepseek-v4-flash
问题: 北京现在天气怎么样？
----------------------------------------------
[模型说] 我要调用工具: get_weather({"city": "北京"})
[调用方] 我已执行工具，结果是: 多云，25℃，东北风 3 级
[模型最后说] 北京现在多云，气温25℃，东北风3级。
```

## 它证明的事

- **模型只会说**：它把「我想查北京天气」编码成一个 JSON（`tool_calls`），并没有真的联网。
- **调用方负责做**：真正去查天气（这里是查一张本地表）的是 `get_weather()`，是**你的代码**在执行。
- **回喂再答**：调用方把工具结果塞回对话，模型基于结果生成最终回答。

## 常见坑

1. **Q: 想换模型？**
   A: `export LLM_MODEL=你的模型名` 覆盖（默认 `deepseek-v4-flash`）。

2. **Q: 报 401 `Invalid API key`？**
   A: 确认已经 `export DEEPSEEK_API_KEY=sk-...` 且当前 shell 生效（`echo $DEEPSEEK_API_KEY` 查看）。

3. **Q: 请求超时 / 网络问题？**
   A: DeepSeek API 需要能直连（api.deepseek.com）。跨国网络可能需要代理，把代理地址设到环境变量。

4. **Q: Java 报 `cannot find symbol` 或版本错误？**
   A: 确认 `java -version` 是 21+（本文用到文本块等新特性）。旧 JDK 不支持。

5. **Q: Java 版代码里为什么手写 JSON 解析？**
   A: 为了零依赖演示。API 返回的 `arguments` 是「字符串形态的 JSON」（内含 `\"` 转义），需要先反转义再取字段——这正是真实工程里非用 JSON 库不可的原因，正文也讲了。

## 文件

- `main.py` — Python 完整闭环：声明工具 → 模型回 tool_calls → 调用方执行 → 回喂 → 最终回答
- `probe.py` — Python 探测脚本：对比「无 tools」vs「带 tools」时模型输出形状的根本差异
- `loop.py` — Python 延伸：把一轮改造成 while 循环（Agent 雏形），支持多工具并行
- `java/Main.java` — Java 21 等价实现（单文件，零依赖）