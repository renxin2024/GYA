#!/usr/bin/env python3
"""C07 记忆篇：文本向量化层（真实 Embedding + 离线兜底）。

两层：
1. 真实 Embedding：调用 Ollama 的 bge-m3（1024 维），经 hermes-gateway 的
   stream 代理暴露在宿主机 127.0.0.1:11434。语义检索的"生产路径"。
2. 离线兜底（TF-IDF）：无 Embedding 服务时，用纯 Python 的 TF-IDF 向量做
   检索，保证"服务没起"也能跑通检索逻辑的回归测试。

设计原则（系列铁律）：
- 真实调用依赖（urllib 访问 Embedding 服务）延迟到函数内部，不写在模块顶部，
  这样离线纯函数测试不会被"服务不可达"堵死。
- Embedding 地址从环境变量读，Key 不进代码、不进 Trace。
"""

from __future__ import annotations

import json
import math
import os
import urllib.request
from collections import Counter
from typing import Sequence

# Embedding 服务地址：默认走 hermes-gateway 的 stream 代理（宿主机 127.0.0.1）。
EMBEDDING_URL = os.environ.get("EMBEDDING_URL", "http://127.0.0.1:11434")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "bge-m3")


# ---------------------------------------------------------------
# 真实 Embedding：Ollama bge-m3
# ---------------------------------------------------------------
def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """用 bge-m3 批量向量化，返回与输入等长的浮点向量列表。

    失败时抛 RuntimeError，调用方决定是否降级到 TF-IDF。
    """
    if not texts:
        return []
    payload = {"model": EMBEDDING_MODEL, "prompt": list(texts)}
    req = urllib.request.Request(
        f"{EMBEDDING_URL.rstrip('/')}/api/embeddings",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())
    except Exception as e:  # noqa: BLE001 — 统一转成明确的运行时错误
        raise RuntimeError(f"Embedding 服务不可达：{e}") from e
    return [item for item in body["embedding"]]


def embed_one(text: str) -> list[float]:
    """Ollama /api/embeddings 一次只收一个 prompt（不走批量数组）。"""
    payload = {"model": EMBEDDING_MODEL, "prompt": text}
    req = urllib.request.Request(
        f"{EMBEDDING_URL.rstrip('/')}/api/embeddings",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Embedding 服务不可达：{e}") from e
    return body["embedding"]


# ---------------------------------------------------------------
# 离线兜底：TF-IDF 向量（纯 Python，零依赖）
# ---------------------------------------------------------------
_STOP = {"的", "了", "是", "在", "我", "你", "他", "她", "它", "们", "什么",
         "那个", "这个", "一个", "喜欢", "用户", "还有", "以及", "就是", "会"}


def _tokenize(text: str) -> list[str]:
    """中文按字 bigram，英文按词。演示级分词，够 TF-IDF 兜底用。"""
    tokens: list[str] = []
    # 中文 bigram
    for i in range(len(text) - 1):
        a, b = text[i], text[i + 1]
        if "\u4e00" <= a <= "\u9fff" and "\u4e00" <= b <= "\u9fff":
            t = a + b
            if t not in _STOP:
                tokens.append(t)
    # 英文词
    for w in text.split():
        if w.isascii() and len(w) > 1:
            tokens.append(w.lower())
    return tokens


def tfidf_matrix(docs: Sequence[str]) -> tuple[list[list[float]], list[str]]:
    """对一组文档做 TF-IDF 向量化，返回 (矩阵, 词表)。

    这是"服务不可达"时的确定性兜底，只用于回归，不冒充模型行为。
    """
    tokenized = [_tokenize(d) for d in docs]
    vocab = sorted({t for toks in tokenized for t in toks})
    df = Counter()
    for toks in tokenized:
        for t in set(toks):
            df[t] += 1
    n = len(docs)
    matrix = []
    for toks in tokenized:
        tf = Counter(toks)
        vec = []
        for t in vocab:
            if tf[t] == 0:
                vec.append(0.0)
            else:
                idf = math.log((n + 1) / (df[t] + 1)) + 1.0
                vec.append((1 + math.log(tf[t])) * idf)
        matrix.append(vec)
    return matrix, vocab


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
