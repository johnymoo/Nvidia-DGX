#!/usr/bin/env python3
"""Pinned f277b3d DS4 performance characterization with strict validity gates."""

import json
import math
import os
import threading
import time
import urllib.request


URL = os.environ.get("URL", "http://127.0.0.1:8890/v1").rstrip("/")
MODEL = os.environ.get("MODEL", "deepseek-v4-flash-0731")
TAG = os.environ.get("TAG", "official-0731-patch4")
RESULT_PATH = os.environ.get("RESULT_PATH", "")

PEAK = [
    ("count300", "Print the numbers 1 to 300, one per line, exact format N. No commentary.", 1200),
    ("mult12", "Print the full 12x12 multiplication table, one line per pair, format A x B = C. No commentary.", 900),
    ("json60", 'Output a JSON array of 60 objects, each exactly {"id":N,"name":"user_N","active":true}. JSON only.', 800),
    ("bst", "Implement a binary search tree in Python with insert, search, delete, in-order traversal, docstrings and usage examples. Code only.", 600),
    ("story", "Write a 200-word story about an engineer debugging a distributed system at 3am.", 400),
]
CONC_PROMPT = (
    "Implement a binary search tree in Python with insert, search, delete and in-order "
    "traversal. Include docstrings and two usage examples. Code only."
)
WARMUP = [
    ("Implement a binary search tree in Python with insert, search, delete and in-order traversal. Include docstrings and two usage examples.", 700),
    ("Write a 300-word explanation of how speculative decoding works.", 600),
    ("Compute the running sum of the first 40 prime numbers, showing each step.", 600),
    ('Output a JSON array of 40 objects, each {"id":N,"name":"user_N"}. JSON only.', 600),
]


def post(prompt, max_tokens, temp=0.0, timeout=900):
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temp,
    }
    req = urllib.request.Request(
        URL + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        payload = json.load(response)
    wall = time.perf_counter() - started
    usage = payload.get("usage") or {}
    completion = int(usage.get("completion_tokens") or 0)
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    if completion <= 0 or wall <= 0 or not math.isfinite(wall):
        raise RuntimeError(f"invalid statistics completion={completion} wall={wall}")
    return {"completion_tokens": completion, "prompt_tokens": prompt_tokens, "wall_seconds": wall}


def run_warmup(result):
    for index, (prompt, max_tokens) in enumerate(WARMUP, start=1):
        row = post(prompt, max_tokens)
        row["round"] = index
        result["warmup"].append(row)
        print(f"warmup {index}/4: {row['completion_tokens']} tokens in {row['wall_seconds']:.2f}s", flush=True)


def run_peak(result):
    for label, prompt, max_tokens in PEAK:
        attempts = [post(prompt, max_tokens), post(prompt, max_tokens)]
        best = max(attempts, key=lambda row: row["completion_tokens"] / row["wall_seconds"])
        best["tokens_per_second"] = best["completion_tokens"] / best["wall_seconds"]
        result["single_stream"].append({"label": label, "attempts": attempts, "best": best})
        print(f"single {label}: {best['completion_tokens']} tokens / {best['wall_seconds']:.2f}s = {best['tokens_per_second']:.2f} tok/s", flush=True)


def run_concurrency(result):
    for concurrency in (1, 2, 4, 6):
        rows = []
        errors = []
        lock = threading.Lock()

        def worker():
            try:
                row = post(CONC_PROMPT, 400)
                with lock:
                    rows.append(row)
            except Exception as exc:  # surfaced after every thread joins
                with lock:
                    errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=worker) for _ in range(concurrency)]
        started = time.perf_counter()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        wall = time.perf_counter() - started
        if errors or len(rows) != concurrency or wall <= 0:
            raise RuntimeError(f"concurrency {concurrency} invalid: rows={len(rows)} errors={errors}")
        total = sum(row["completion_tokens"] for row in rows)
        aggregate = total / wall
        result["concurrency"].append(
            {
                "concurrency": concurrency,
                "requests": len(rows),
                "completion_tokens": total,
                "wall_seconds": wall,
                "aggregate_tokens_per_second": aggregate,
                "rows": rows,
            }
        )
        print(f"c{concurrency}: {total} tokens / {wall:.2f}s = {aggregate:.2f} aggregate tok/s", flush=True)


def run_prefill(result):
    filler = (
        "Distributed inference on GB10 schedules prefill and decode in the same step; "
        "long prompts dominate the step budget and delay in-flight decodes. "
    )
    for target in (0, 32000, 100000):
        prompt = "Reply with one word: ready."
        if target:
            repeats = max(1, int(target / 22))
            prompt = (filler * repeats)[: target * 4] + "\nSummarize in one sentence."
        row = post(prompt, 1, timeout=1200)
        prompt_tokens = row["prompt_tokens"]
        throughput = prompt_tokens / row["wall_seconds"] if prompt_tokens else 0.0
        if target and throughput <= 0:
            raise RuntimeError(f"prefill {target} produced invalid throughput")
        row.update({"target_tokens": target, "prefill_tokens_per_second": throughput})
        result["prefill"].append(row)
        print(f"prefill {target}: prompt={prompt_tokens} TTFT={row['wall_seconds']:.2f}s rate={throughput:.2f} tok/s", flush=True)


def main():
    result = {
        "schema_version": 1,
        "upstream_revision": "f277b3dfa718a5962bed64e69e7e640a5384ec2f",
        "tag": TAG,
        "url": URL,
        "model": MODEL,
        "warmup": [],
        "single_stream": [],
        "concurrency": [],
        "prefill": [],
        "status": "failed",
    }
    try:
        run_warmup(result)
        run_peak(result)
        run_concurrency(result)
        run_prefill(result)
        result["status"] = "passed"
        return_code = 0
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(f"BENCHMARK FAILED: {result['error']}", flush=True)
        return_code = 1
    if RESULT_PATH:
        with open(RESULT_PATH, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
