#!/usr/bin/env python3
"""Small OpenAI-compatible stability/concurrency check for agent endpoints."""

import concurrent.futures
import json
import os
import statistics
import sys
import time
import urllib.request


BASE_URL = os.environ.get("DSPARK_BASE_URL", "http://127.0.0.1:8888/v1")
MODEL = os.environ.get("DSPARK_MODEL", "deepseek-v4-flash-dspark")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "256"))
RESULT_PATH = os.environ.get("RESULT_PATH", "")
CONCURRENCY_LIST = [
    int(x) for x in os.environ.get("CONCURRENCY", "1,2,4,6").split(",") if x.strip()
]


def make_prompt(i: int) -> str:
    filler = " ".join(f"token{i}_{j}" for j in range(420))
    return (
        "Write a concise implementation note in plain English. "
        "Stay in English. Do not repeat characters. Do not output XML. "
        "Keep writing useful detail until the answer is complete.\n\n"
        f"Context salt {i}: {filler}"
    )


def looks_bad(text: str) -> bool:
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    repeated = any(ch * 18 in text for ch in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    leaked = any(marker in text.lower() for marker in ("<available_skills", "<tool", "</tool", "<think>"))
    return cjk > 0 or repeated or leaked


def request_one(i: int) -> dict:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": make_prompt(i)}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
    }
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=420) as r:
        data = json.load(r)
    dt = time.perf_counter() - t0
    usage = data.get("usage") or {}
    content = data["choices"][0]["message"].get("content") or ""
    completion = int(usage.get("completion_tokens") or 0)
    if completion <= 0 or not content.strip():
        raise RuntimeError(f"empty output completion_tokens={completion}")
    return {
        "id": i,
        "seconds": round(dt, 3),
        "completion_tokens": completion,
        "tok_s": round(completion / dt, 2) if dt else 0,
        "finish_reason": data["choices"][0].get("finish_reason"),
        "bad_output": looks_bad(content),
        "sample": content[:200],
    }


def run(concurrency: int) -> dict:
    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        rows = list(ex.map(request_one, range(concurrency)))
    wall = time.perf_counter() - start
    total = sum(r["completion_tokens"] for r in rows)
    return {
        "concurrency": concurrency,
        "success": f"{sum(not r['bad_output'] for r in rows)}/{len(rows)}",
        "max_tokens": MAX_TOKENS,
        "wall_seconds": round(wall, 3),
        "completion_tokens": total,
        "aggregate_tok_s": round(total / wall, 2) if wall else 0,
        "per_request_tok_s_mean": round(statistics.mean(r["tok_s"] for r in rows), 2),
        "bad_outputs": sum(1 for r in rows if r["bad_output"]),
        "rows": rows,
    }


def main() -> int:
    result = {"schema_version": 1, "url": BASE_URL, "model": MODEL, "runs": [], "status": "failed"}
    try:
        for concurrency in CONCURRENCY_LIST:
            row = run(concurrency)
            result["runs"].append(row)
            if row["bad_outputs"] > 0:
                raise RuntimeError(f"c{concurrency} produced {row['bad_outputs']} invalid outputs")
        result["status"] = "passed"
        return_code = 0
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return_code = 1
    if RESULT_PATH:
        with open(RESULT_PATH, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
            handle.write("\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return return_code


if __name__ == "__main__":
    sys.exit(main())
