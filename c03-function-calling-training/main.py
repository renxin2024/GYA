#!/usr/bin/env python3
"""C03：记录模型候选调用；绝不执行订单工具。"""
from __future__ import annotations
import argparse, copy, json, os, sys, urllib.request

CASES = {
    "paid-refund": ("订单 O-100 我已经付款了，想退款。", "订单 O-100：已支付，尚未发货。", "refund_order", "O-100"),
    "unpaid-cancel": ("订单 O-200 还没付款，我不想买了。", "订单 O-200：未支付，尚未发货。", "cancel_order", "O-200"),
    "missing-order": ("我不想要这个订单了，帮我处理一下。", "未提供订单号；Runtime 没有可验证的订单或支付状态。", None, None),
    "no-intent": ("订单一般多久能送到？", "没有指定订单；用户没有退款或取消意图。", None, None),
}
TOOLS = [{"type":"function","function":{"name":"refund_order","description":"仅当 Runtime 已验证订单已支付时，提交退款请求。状态未知必须先澄清，不能调用。","parameters":{"type":"object","properties":{"order_id":{"type":"string"}},"required":["order_id"],"additionalProperties":False}}},{"type":"function","function":{"name":"cancel_order","description":"仅当 Runtime 已验证订单未支付且未发货时，提交取消请求。状态未知必须先澄清，不能调用。","parameters":{"type":"object","properties":{"order_id":{"type":"string"}},"required":["order_id"],"additionalProperties":False}}}]

def tools(profile):
    result = copy.deepcopy(TOOLS)
    if profile == "swapped": result[0]["function"]["description"], result[1]["function"]["description"] = result[1]["function"]["description"], result[0]["function"]["description"]
    return result

def payload(mode, case, profile):
    user, context, _, _ = CASES[case]; schema = tools(profile)
    runtime = "订单状态由 Runtime 验证后注入，不是让你猜测的事实。\n[Runtime verified context]\n" + context + "\n只有状态满足 description 才请求工具；信息不足时自然语言追问。本程序只记录候选调用，绝不执行订单动作。"
    if mode == "prompt-only":
        contract = "\n".join(f"- {x['function']['name']}(order_id): {x['function']['description']}" for x in schema)
        runtime += "\n工具约定：\n" + contract + "\n需要调用时只输出 {\"name\":\"工具名\",\"arguments\":{\"order_id\":\"...\"}}；否则自然语言回复。"
    result = {"model":os.getenv("LLM_MODEL", "deepseek-v4-flash"),"messages":[{"role":"system","content":runtime},{"role":"user","content":user}],"stream":False}
    if mode == "native-tools": result["tools"] = schema
    return result

def observe(mode, message):
    if mode == "native-tools":
        calls = message.get("tool_calls") or []
        if not calls: return None, None
        fn = calls[0]["function"]; return fn["name"], json.loads(fn["arguments"])
    try:
        result = json.loads(message.get("content") or ""); return result.get("name"), result.get("arguments")
    except json.JSONDecodeError: return None, None

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--mode",choices=["prompt-only","native-tools","all"],default="all"); parser.add_argument("--case",choices=[*CASES,"all"],default="all"); parser.add_argument("--description-profile",choices=["precise","swapped"],default="precise"); parser.add_argument("--dry-run",action="store_true"); args=parser.parse_args()
    key=os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    if not args.dry_run and not key: print("请设置 LLM_API_KEY 或 DEEPSEEK_API_KEY；--dry-run 不需要 Key。",file=sys.stderr); return 2
    bad=0
    for mode in (["prompt-only","native-tools"] if args.mode=="all" else [args.mode]):
      for case in (CASES if args.case=="all" else [args.case]):
        request=payload(mode,case,args.description_profile)
        if args.dry_run: print(json.dumps(request,ensure_ascii=False,indent=2)); continue
        req=urllib.request.Request(os.getenv("LLM_API_URL","https://api.deepseek.com/chat/completions"),data=json.dumps(request,ensure_ascii=False).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+key},method="POST")
        with urllib.request.urlopen(req,timeout=60) as response: message=json.loads(response.read().decode())["choices"][0]["message"]
        name, arguments=observe(mode,message); _,_,wanted,order=CASES[case]; passed=(name is None if wanted is None else name==wanted and arguments=={"order_id":order}); print(f"{mode}/{case}: observed={name} arguments={arguments} result={'PASS' if passed else 'CHECK'}"); bad += not passed
    return int(bool(bad))
if __name__ == "__main__": raise SystemExit(main())
