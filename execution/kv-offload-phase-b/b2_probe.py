#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""B2 offload-hit correctness probe for the Phase B campaign.

Usage:
  b2_probe.py needle                 record baseline answer (run BEFORE flood)
  b2_probe.py flood  [ntoks_target]  flood fresh tokens (default 1.6M)
  b2_probe.py recheck                re-issue needle, compare byte-identical
  b2_probe.py metrics                print vllm:kv_offload_* + cache gauges

Needle: 17,000 random words (seed 90001) with a unique marker token buried
mid-prompt; asks the model to quote the marker. temperature 0.
"""
import json
import random
import string
import sys
import time
import urllib.request

API = "http://192.168.88.181:8890/v1/chat/completions"
MODEL = "deepseek-v4-flash-0731"
MARKER = "AURORA-73-KESTREL"
STATE = "/tmp/b2-needle-state.json"


def rand_words(n_words: int, seed: int) -> str:
    rng = random.Random(seed)
    words = []
    for _ in range(n_words):
        words.append("".join(rng.choices(string.ascii_lowercase,
                                         k=rng.randint(3, 9))))
    return " ".join(words)


def needle_prompt() -> str:
    body = rand_words(17000, 90001).split()
    body[len(body) // 2] = MARKER
    return " ".join(body)


def request(messages, max_tokens=16, timeout=1200):
    t0 = time.perf_counter()
    body = json.dumps({
        "model": MODEL,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": max_tokens,
    })
    req = urllib.request.Request(
        API, data=body.encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.load(r)
    dt = time.perf_counter() - t0
    return out, dt


def usage_bits(out):
    u = out.get("usage", {})
    ptd = u.get("prompt_tokens_details") or {}
    return {
        "prompt_tokens": u.get("prompt_tokens"),
        "cached_tokens": ptd.get("cached_tokens"),
        "completion_tokens": u.get("completion_tokens"),
    }


def do_needle():
    msgs = [{"role": "user", "content": needle_prompt() + "\n\nA unique "
             "identifier token is buried in the text above. Reply with "
             "ONLY that identifier token and nothing else."}]
    out, dt = request(msgs, max_tokens=16)
    ans = out["choices"][0]["message"]["content"]
    rec = {"answer": ans, "ttft_wall_s": round(dt, 2), **usage_bits(out)}
    with open(STATE, "w") as f:
        json.dump(rec, f, indent=1)
    print(json.dumps(rec, indent=1))
    ok = MARKER in ans
    print("NEEDLE-BASELINE:", "PASS" if ok else "FAIL")


def do_flood(target=1_600_000):
    sent = 0
    i = 0
    while sent < target:
        words = 21000 + (i % 3) * 1000  # ~26-29K tokens per shot
        p = rand_words(words, 700000 + i)
        msgs = [{"role": "user", "content":
                 p + "\n\nSummarize the text above in one word."}]
        t0 = time.perf_counter()
        out, dt = request(msgs, max_tokens=8, timeout=1800)
        n = out.get("usage", {}).get("prompt_tokens", 0)
        sent += n or 0
        print(f"[flood {i}] +{n} tok ({dt:.0f}s) total={sent}")
        i += 1
    print(f"FLOOD-DONE total_prompt_tokens={sent}")


def do_recheck():
    with open(STATE) as f:
        base = json.load(f)
    msgs = [{"role": "user", "content": needle_prompt() + "\n\nA unique "
             "identifier token is buried in the text above. Reply with "
             "ONLY that identifier token and nothing else."}]
    out, dt = request(msgs, max_tokens=16)
    ans = out["choices"][0]["message"]["content"]
    rec = {"answer": ans, "ttft_wall_s": round(dt, 2), **usage_bits(out)}
    print(json.dumps(rec, indent=1))
    print("BASELINE:", json.dumps(base, indent=1))
    ok = (MARKER in ans
          and ans.strip() == base["answer"].strip()
          and (rec["cached_tokens"] or 0) > 0
          and dt <= 30.0)
    print("B2-RECHECK:", "PASS" if ok else "FAIL")


def do_metrics():
    req = urllib.request.Request("http://192.168.88.181:8890/metrics")
    with urllib.request.urlopen(req, timeout=20) as r:
        for ln in r.read().decode().splitlines():
            if ln.startswith(("vllm:kv_offload", "vllm:gpu_prefix_cache",
                              "vllm:cache_config", "vllm:num_requests")):
                print(ln)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "metrics"
    if cmd == "needle":
        do_needle()
    elif cmd == "flood":
        do_flood(int(sys.argv[2]) if len(sys.argv) > 2 else 1_600_000)
    elif cmd == "recheck":
        do_recheck()
    elif cmd == "metrics":
        do_metrics()
    else:
        print(__doc__)
        sys.exit(2)
