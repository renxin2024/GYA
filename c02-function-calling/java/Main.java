import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * C02 演示（Java 21 版）：Function Calling 第一性原理
 *
 * 模型并没有"学会"调用工具——它只是输出了一个 JSON 格式的工具调用请求，
 * 真正执行函数的是调用方（也就是本程序）的代码。
 *
 * 用法（JDK 21，单文件运行，无需 Maven/Jar）：
 *   export DEEPSEEK_API_KEY=sk-xxx
 *   java Main.java
 *
 * 依赖：仅 JDK 21 标准库（java.net.http + 正则提取 JSON 字段）。
 * JSON 字段提取用正则是为了保持"零依赖"；生产环境请用 Jackson/Gson。
 */
public class Main {

    static final String API_URL = System.getenv().getOrDefault("LLM_API_URL", "https://api.deepseek.com/chat/completions");
    static final String API_KEY = System.getenv().getOrDefault("DEEPSEEK_API_KEY", "");
    static final String MODEL = System.getenv().getOrDefault("LLM_MODEL", "deepseek-v4-flash");

    // ---------------------------------------------------------------
    // 1. 声明模型"可以用"哪些工具。（声明 ≠ 执行）
    // ---------------------------------------------------------------
    static final String TOOLS_JSON = """
            [{
              "type": "function",
              "function": {
                "name": "get_weather",
                "description": "查询指定城市的当前天气。城市例：北京、上海、深圳",
                "parameters": {
                  "type": "object",
                  "properties": {
                    "city": { "type": "string", "description": "城市名" }
                  },
                  "required": ["city"]
                }
              }
            }]
            """.strip();

    static final java.util.Map<String, String> FAKE_WEATHER = java.util.Map.of(
            "北京", "多云，25℃，东北风 3 级",
            "上海", "阵雨，28℃，东南风 2 级",
            "深圳", "晴，31℃，南风 2 级");

    /** 真正执行工具的函数——它才是"会干活"的那一方。 */
    static String getWeather(String city) {
        return FAKE_WEATHER.getOrDefault(city, "暂无 " + city + " 的天气数据");
    }

    // ------------------- 极简 JSON 提取（零依赖方案） -------------------

    /** 从一段 JSON 中提取第一个字符串字段的值。 */
    static String jsonString(String json, String key) {
        Matcher m = Pattern.compile("\"" + key + "\"\\s*:\\s*\"((?:\\\\.|[^\"\\\\])*)\"")
                .matcher(json);
        if (m.find()) return m.group(1);
        return "";
    }

    /** 从 response JSON 里取出完整的 tool_calls 数组文本。 */
    static String extractToolCalls(String responseJson) {
        int i = responseJson.indexOf("\"tool_calls\"");
        if (i < 0) return null;
        // 从 tool_calls: 后面那个 [ 开始，匹配到配对的 ]
        int start = responseJson.indexOf('[', i);
        int depth = 0;
        for (int j = start; j < responseJson.length(); j++) {
            char c = responseJson.charAt(j);
            if (c == '[') depth++;
            else if (c == ']' && --depth == 0) return responseJson.substring(start, j + 1);
        }
        return null;
    }

    /** 从整个 tool_calls 数组里取出第一个调用的 arguments 对象文本。 */
    static String firstArguments(String toolCallsJson) {
        int i = toolCallsJson.indexOf("\"arguments\"");
        if (i < 0) return "";
        int start = toolCallsJson.indexOf('{', i);
        int depth = 0;
        for (int j = start; j < toolCallsJson.length(); j++) {
            char c = toolCallsJson.charAt(j);
            if (c == '{') depth++;
            else if (c == '}' && --depth == 0)
                // API 里 arguments 是"字符串形态的 JSON"（含 \\\" 转义），解一次转义再返回
                return unescapeJson(toolCallsJson.substring(start, j + 1));
        }
        return "{}";
    }

    /** 极简 JSON 反转义：把 \\\" → \"、\\\\ → \\（零依赖方案；生产请用 Jackson/Gson）。 */
    static String unescapeJson(String s) {
        return s.replace("\\\\", "\u0000")     // 先保护 \\ 
                 .replace("\\\"", "\"")
                 .replace("\u0000", "\\");
    }

    /** 把任意字符串转成 JSON 字符串字面量（极简：只转义引号和反斜杠；生产用 Jackson/Gson）。 */
    static String toJsonString(String s) {
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    // ------------------- API 调用 -------------------

    /** 发送一次 chat/completions 请求，返回原始响应 JSON。 */
    static String call(String messagesJson, String toolsJson) throws Exception {
        String payload = """
                {
                  "model": "%s",
                  "messages": %s,
                  "tools": %s,
                  "stream": false
                }
                """.formatted(MODEL, messagesJson, toolsJson == null ? "null" : toolsJson);

        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(API_URL))
                .header("Content-Type", "application/json")
                .header("Authorization", "Bearer " + API_KEY)
                .POST(HttpRequest.BodyPublishers.ofString(payload))
                .build();

        HttpResponse<String> resp = HttpClient.newHttpClient().send(req,
                HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) {
            throw new RuntimeException("HTTP " + resp.statusCode() + ": " + resp.body());
        }
        return resp.body();
    }

    public static void main(String[] args) throws Exception {
        if (API_KEY.isEmpty()) {
            System.out.println("请先设置 DEEPSEEK_API_KEY 环境变量（https://platform.deepseek.com 获取）");
            System.exit(1);
        }

        String question = "北京现在天气怎么样？";
        System.out.printf("模型: %s%n问题: %s%n%s%n", MODEL, question, "-".repeat(46));

        // 第一轮：把问题 + 工具声明一起发给模型
        String messages = """
                [{"role": "user", "content": "%s"}]
                """.formatted(question);
        String r = call(messages, TOOLS_JSON);

        String toolCalls = extractToolCalls(r);
        if (toolCalls != null) {
            // 模型说："我想调用 get_weather(北京)" —— 注意它只说了，没做
            String arguments = firstArguments(toolCalls);
            String city = jsonString(arguments, "city");
            String toolCallId = jsonString(toolCalls, "id");
            System.out.println("[模型说] 我要调用工具: get_weather({\"city\": \"" + city + "\"})");

            // 现在调用方（我们的代码）真正执行
            String result = getWeather(city);
            System.out.println("[调用方] 我已执行工具，结果是: " + result);

            // 回喂：必须按 API 语义带上 assistant 的 tool_calls 记录，
            // 再接一条 role=tool 的工具结果消息。
            // 注意 arguments 作为 JSON 字符串值需要再次转义（生产用 Jackson/Gson 序列化）。
            String messages2 = """
                    [
                      {"role": "user", "content": "%s"},
                      {"role": "assistant", "content": null, "tool_calls": [
                          {"id": "%s", "type": "function",
                           "function": {"name": "get_weather", "arguments": "%s"}}
                      ]},
                      {"role": "tool", "tool_call_id": "%s", "content": "%s"}
                    ]
                    """.formatted(question, toolCallId, toJsonString(arguments), toolCallId, result);

            // 第二轮：模型拿到工具结果，生成最终回答
            String r2 = call(messages2, null);
            String content = jsonString(r2, "content");
            System.out.println("[模型最后说] " + content);
        } else {
            String content = jsonString(r, "content");
            System.out.println("[模型直接回答] " + content);
        }
    }
}