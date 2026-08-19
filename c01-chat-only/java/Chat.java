import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.ArrayList;
import java.util.Scanner;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * C01 演示（Java 21 版）：一个只会说话的模型（命令行聊天）
 *
 * 启动后你就能和模型对话——它说的每句话，底层都是一次
 * "给定前文 token，预测下一个 token" 的重复。
 *
 * 用法（JDK 21，单文件运行，无需 Maven/Jar）：
 *   export DEEPSEEK_API_KEY=sk-xxx
 *   java Chat.java
 *
 * 依赖：仅 JDK 21 标准库（java.net.http）。
 */
public class Chat {

    static final String API_URL = System.getenv().getOrDefault("LLM_API_URL", "https://api.deepseek.com/chat/completions");
    static final String API_KEY = System.getenv().getOrDefault("DEEPSEEK_API_KEY", "");
    static final String MODEL = System.getenv().getOrDefault("LLM_MODEL", "deepseek-v4-flash");

    /** 简易历史：保存 {role, content} 对。 */
    static final ArrayList<String> HISTORY = new ArrayList<>();  // 每项是 "role\tcontent"

    /** 把整个对话历史发给模型，返回它补全出来的下一个回复。 */
    static String ask(String userText) throws Exception {
        HISTORY.add("user\t" + userText);

        // 拼 messages 数组（极简字符串拼接，不用 JSON 库）
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < HISTORY.size(); i++) {
            String[] parts = HISTORY.get(i).split("\t", 2);
            if (i > 0) sb.append(",");
            sb.append("{\"role\":\"")
              .append(parts[0])
              .append("\",\"content\":\"")
              .append(escape(parts[1]))
              .append("\"}");
        }
        sb.append("]");

        String payload = """
                {"model": "%s", "messages": %s, "stream": false}
                """.formatted(MODEL, sb);

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

        String reply = jsonString(resp.body(), "content");
        HISTORY.add("assistant\t" + reply);
        return reply;
    }

    /** 极简转义：内容里的引号/反斜杠（生产用 Jackson/Gson）。 */
    static String escape(String s) {
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    /** 提取 JSON 里第一个字符串字段的值。 */
    static String jsonString(String json, String key) {
        Matcher m = Pattern.compile("\"" + key + "\"\\s*:\\s*\"((?:\\\\.|[^\"\\\\])*)\"")
                .matcher(json);
        return m.find() ? m.group(1) : "";
    }

    public static void main(String[] args) throws Exception {
        if (API_KEY.isEmpty()) {
            System.out.println("请先设置 DEEPSEEK_API_KEY 环境变量（https://platform.deepseek.com 获取）");
            System.exit(1);
        }

        System.out.println("模型: " + MODEL);
        System.out.println("你正在和一个只会说话的模型聊天。输入 exit 退出。\n");

        try (Scanner in = new Scanner(System.in)) {
            while (true) {
                System.out.print("你 > ");
                String line = in.hasNextLine() ? in.nextLine().trim() : "";
                if (line.isEmpty()) continue;
                if (line.equalsIgnoreCase("exit") || line.equalsIgnoreCase("quit")
                        || line.equals("退出")) break;
                System.out.println("模型 > " + ask(line) + "\n");
            }
        }
    }
}