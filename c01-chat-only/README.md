# C01 演示：只会说话的模型（命令行聊天）

一个简洁的命令行聊天程序。跑起来之后，你就能亲手体验「模型只会说话」这件事。

支持 **Python 3.10+** 与 **Java 21** 两个版本，任选其一运行。

## 版本总览

| 版本 | 位置 | 环境 | 运行方式 |
|------|------|------|---------|
| Python（教程正文用） | `chat.py` | Python 3.10+，零依赖 | `python3 chat.py` |
| Java 21 | `java/Chat.java` | JDK 21，零依赖（单文件运行） | `java Chat.java` |

（Java 版用 JDK 自带 `java.net.http.HttpClient` 发请求 + 正则提取 JSON 字段，刻意零依赖；生产环境请换 Jackson/Gson 等 JSON 库。）

## 获取 API Key（约 2 分钟，两种版本通用）

1. 打开 https://platform.deepseek.com 注册/登录
2. 左侧「API Keys」→「创建 API Key」，复制 `sk-...`
3. （按量付费需先充值：控制台「充值」最低 10 元）

## 运行

```bash
export DEEPSEEK_API_KEY=sk-你的key

# Python 版
python3 chat.py

# Java 21 版（任选其一；需要 JDK 21，见下）
cd java && java Chat.java
```

看到提示后直接输入文字回车，就能对话。输入 `exit` / `quit` / `退出` 退出。

## 预期输出

```
你 > 你好，你是谁？
模型 > 你好！我是一个 AI 助手……
你 > 你会查天气吗？
模型 > 我没有实时访问互联网的能力……
你 > exit
```

- 能连续多轮对话（模型记得前文——因为每次请求都把整个历史发回去了）
- 问「你能查天气/订机票/执行操作吗」→ 模型回答「不能」（它只会生成文本）

## 环境要求

| 版本 | 要求 | 验证 |
|------|------|------|
| Python | 3.10+ | `python3 --version` |
| Java | JDK 21（LTS） | `java -version` 显示 `21.0.x` |

Java 版需要 JDK 21：macOS `brew install openjdk@21`；Ubuntu/Debian `sudo apt install openjdk-21-jdk-headless`；Windows 从 [Adoptium](https://adoptium.net) 下载。

## 文件

- `chat.py` — Python 版（40 行）
- `java/Chat.java` — Java 21 等价实现（单文件，零依赖）