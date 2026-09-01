#!/usr/bin/env python3
"""Measure uncached prefill TTFT vs context length on the private DS service.

Sends fresh random-token prompts (no prefix-cache hits) of increasing size,
max_tokens=1, and records wall latency + usage. Also samples an optional
concurrent short request to measure head-of-line blocking.
"""
import json
import random
import string
import sys
import time
import urllib.request

API = "http://192.168.88.181:8890/v1/chat/completions"
MODEL = "deepseek-v4-flash-0731"


def rand_words(n_words: int, seed: int) -> str:
    rng = random.Random(seed)
    words = []
    for _ in range(n_words):
        w = "".join(rng.choices(string.ascii_lowercase, k=rng.randint(3, 9)))
        words.append(w)
    return " ".join(words)


def request(prompt: str, max_tokens: int = 1, timeout: int = 1200):
    body = json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
            "chat_template_kwargs": {"thinking": False},
        }
    ).encode()
    req = urllib.request.Request(
        API, data=body, headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    dt = time.time() - t0
    return dt, data.get("usage", {})


def main():
    n_words = int(sys.argv[1])
    seed = int(sys.argv[2])
    prompt = rand_words(n_words, seed)
    dt, usage = request(prompt)
    print(
        json.dumps(
            {
                "n_words": n_words,
                "seed": seed,
                "latency_s": round(dt, 2),
                "prompt_tokens": usage.get("prompt_tokens"),
                "cached_tokens": (usage.get("prompt_tokens_details") or {}).get(
                    "cached_tokens"
                ),
                "tok_per_s": round(usage.get("prompt_tokens", 0) / dt, 1),
            }
        )
    )


if __name__ == "__main__":
    main()
