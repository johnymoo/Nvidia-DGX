#!/usr/bin/env python3
"""Concurrent streaming decode bench (c=2/4) for the GLM-5.3 validation window.

Same protocol as the repo's tests/bench_decode.py (temp 0, thinking off,
400 tokens, structured count / hashmap prose) but with N parallel streams.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

STRUCTURED = "Count from 1 to 200. Output only the numbers, separated by spaces. No other text."
PROSE = (
    "Write a detailed step-by-step explanation of how a hash map works, "
    "including collision handling, resizing, and time complexity. Be thorough."
)


def stream_one(base: str, model: str, prompt: str, max_tokens: int, thinking_kwargs: dict, timeout: float):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "top_p": 1,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": thinking_kwargs,
    }
    req = urllib.request.Request(
        base + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    first = None
    usage = None
    finish = None
    text_parts: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            buf = b""
            while True:
                piece = resp.read1(512)
                if not piece:
                    break
                buf += piece
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line.startswith(b"data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == b"[DONE]":
                        continue
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("usage"):
                        usage = obj["usage"]
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content") or delta.get("reasoning") or ""
                    if content:
                        if first is None:
                            first = time.perf_counter()
                        text_parts.append(content)
                    if choices[0].get("finish_reason"):
                        finish = choices[0]["finish_reason"]
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}", "ttft_s": None, "tok_s": None}
    t1 = time.perf_counter()
    ctoks = int((usage or {}).get("completion_tokens") or 0)
    decode_s = (t1 - first) if first else 0
    return {
        "ttft_s": round(first - t0, 3) if first else None,
        "wall_s": round(t1 - t0, 3),
        "completion_tokens": ctoks,
        "tok_s": round(max(ctoks - 1, 0) / decode_s, 2) if decode_s > 0 and ctoks > 1 else None,
        "finish_reason": finish,
        "text_head": "".join(text_parts)[:100],
        "error": None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8890")
    ap.add_argument("--model", default="GLM-5.3-Flash-EXL3")
    ap.add_argument("--out", required=True)
    ap.add_argument("--prompt", choices=["structured", "prose"], required=True)
    ap.add_argument("--concurrency", type=int, required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--timeout-s", type=float, default=900)
    ap.add_argument("--thinking-kwargs", default='{"enable_thinking": false}')
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    prompt = STRUCTURED if args.prompt == "structured" else PROSE
    thinking_kwargs = json.loads(args.thinking_kwargs)

    trials = []
    for run in range(1, args.runs + 1):
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            rows = list(
                pool.map(
                    lambda _: stream_one(
                        args.base, args.model, prompt, args.max_tokens, thinking_kwargs, args.timeout_s
                    ),
                    range(args.concurrency),
                )
            )
        wall = time.perf_counter() - t0
        ok = [r for r in rows if r.get("error") is None]
        total = sum(r["completion_tokens"] for r in ok)
        trial = {
            "run": run,
            "wall_s": round(wall, 3),
            "success": len(ok),
            "errors": args.concurrency - len(ok),
            "aggregate_tok_s": round(total / wall, 2) if wall > 0 else None,
            "median_ttft_s": round(statistics.median(r["ttft_s"] for r in ok), 3) if ok else None,
            "median_tok_s": round(statistics.median(r["tok_s"] for r in ok), 2) if ok else None,
            "streams": rows,
        }
        print(json.dumps({k: v for k, v in trial.items() if k != "streams"}), flush=True)
        trials.append(trial)

    good = [t for t in trials if t["errors"] == 0]
    rec = {
        "prompt": args.prompt,
        "concurrency": args.concurrency,
        "runs": trials,
        "summary": {
            "median_aggregate_tok_s": round(statistics.median(t["aggregate_tok_s"] for t in good), 2)
            if good
            else None,
            "median_stream_tok_s": round(statistics.median(t["median_tok_s"] for t in good), 2)
            if good
            else None,
        },
    }
    out.write_text(json.dumps(rec, indent=2))
    print("wrote", out, flush=True)
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
