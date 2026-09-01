#!/usr/bin/env python3
"""D1b fast canary: identical prompt twice; 2nd must show cached_tokens > 0.

This is the A1 kill-signal reduced to its fastest form (root-cause doc §8
standing probe). ~1 minute. PASS here does NOT alone pass the arm; FAIL here
kills it immediately.
"""
import hashlib
import json
import random
import string
import sys
import time
import urllib.request

API = "http://192.168.88.181:8890/v1/chat/completions"
MODEL = "deepseek-v4-flash-0731"


def rand_words(n_words, seed):
    rng = random.Random(seed)
    return " ".join("".join(rng.choices(string.ascii_lowercase, k=rng.randint(3, 9))) for _ in range(n_words))


def request(prompt, max_tokens=1, timeout=900):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "chat_template_kwargs": {"thinking": False},
    }).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    dt = time.time() - t0
    u = data.get("usage", {})
    return dt, u.get("prompt_tokens"), (u.get("prompt_tokens_details") or {}).get("cached_tokens")


def main():
    n_words = int(sys.argv[1]) if len(sys.argv) > 1 else 5200  # ≈18K tokens
    prompt = rand_words(n_words, 73001)
    sha = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    d1, pt1, ct1 = request(prompt)
    d2, pt2, ct2 = request(prompt)
    print(json.dumps({
        "prompt_sha": sha,
        "first": {"latency_s": round(d1, 2), "prompt_tokens": pt1, "cached_tokens": ct1},
        "second": {"latency_s": round(d2, 2), "prompt_tokens": pt2, "cached_tokens": ct2},
        "canary_pass": (ct2 or 0) > 0,
    }))
    sys.exit(0 if (ct2 or 0) > 0 else 1)


if __name__ == "__main__":
    main()
