#!/usr/bin/env python3
"""C02 机制探测：验证 DeepSeek 官方 API 带 tools 参数时的真实输出形状。"""
import json, os, urllib.request

API_URL = "https://api.deepseek.com/chat/completions"
API_KEY = os.environ["DEEPSEEK_API_KEY"]
MODEL = "deepseek-v4-flash"

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市的实时天气",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名，如 北京"}
            },
            "required": ["city"]
        }
    }
}]


def call(messages, tools=None):
    payload = {"model": MODEL, "messages": messages, "tools": tools, "stream": False}
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


# A) 无 tools：模型会怎么回答天气问题
msgs_a = [{"role": "user", "content": "北京现在天气怎么样？"}]
print("=== A) 不带 tools ===")
r_a = call(msgs_a)
print(json.dumps(r_a["choices"][0]["message"], ensure_ascii=False, indent=2))

# B) 带 tools：模型应输出 tool_calls
msgs_b = [{"role": "user", "content": "北京现在天气怎么样？"}]
print("=== B) 带 tools ===")
r_b = call(msgs_b, tools=TOOLS)
msg_b = r_b["choices"][0]["message"]
print(json.dumps(msg_b, ensure_ascii=False, indent=2))
print("content=直接回答:", repr(msg_b.get("content")))
print("tool_calls=", json.dumps(msg_b.get("tool_calls"), ensure_ascii=False, indent=2))
