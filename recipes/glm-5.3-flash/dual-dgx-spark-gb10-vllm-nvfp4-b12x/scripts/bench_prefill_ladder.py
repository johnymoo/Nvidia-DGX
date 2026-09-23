#!/usr/bin/env python3
"""Cold-prefill ladder for the GLM-5.3 validation window (runs on the head).

Unique-salt prompts -> guaranteed cold (prefix cache hashes from token 0).
Reports prompt_tokens/TTFT like the repo receipts. Samples /proc/meminfo and
aborts the remaining ladder if MemAvailable drops below the floor (the repo
crashed a head on a long prefill with zero MemAvailable on 2026-09-06).
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

WORDS = (
    "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima "
    "mike november oscar papa quebec romeo sierra tango uniform victor whiskey "
    "xray yankee zulu north south east west river mountain forest harbor meadow"
).split()


def mem_available_mb() -> int:
    with open("/proc/meminfo") as fh:
        for line in fh:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    return -1


class MemoryGuard(threading.Thread):
    def __init__(self, floor_mb: int):
        super().__init__(daemon=True)
        self.floor_mb = floor_mb
        self.low = False
        self.min_seen = None
        self.samples: list[tuple[float, int]] = []
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            mb = mem_available_mb()
            self.samples.append((time.time(), mb))
            if self.min_seen is None or (mb >= 0 and mb < self.min_seen):
                self.min_seen = mb
            if mb >= 0 and mb < self.floor_mb:
                self.low = True
            self._stop.wait(1.0)

    def stop(self):
        self._stop.set()


def build_prompt(target_tokens: int, salt: str) -> str:
    # Measured filler density ~2.25 chars/token (digits + spaces tokenize poorly);
    # calibrated 2026-09-10 against the DS tokenizer, GLM will differ slightly but
    # actual prompt_tokens is always reported. Salt at position 0 => all blocks cold.
    pieces = [f"SALT {salt} "]
    i = 0
    total = 0
    budget = target_tokens * 9 // 4
    while total < budget:
        w = WORDS[i % len(WORDS)]
        pieces.append(f"{i:08d} {w} {i % 97} {salt[:6]} {w.upper()} ")
        total += len(pieces[-1])
        i += 1
    pieces.append("\nIgnore all the filler above. Reply with exactly: ACK")
    return "".join(pieces)


def stream_request(base: str, model: str, prompt: str, max_tokens: int,
                   thinking_kwargs: dict, timeout: float):
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
    t1 = time.perf_counter()
    return {
        "ttft_s": None if first is None else round(first - t0, 3),
        "wall_s": round(t1 - t0, 3),
        "prompt_tokens": int((usage or {}).get("prompt_tokens") or 0),
        "completion_tokens": int((usage or {}).get("completion_tokens") or 0),
        "finish_reason": finish,
        "text": "".join(text_parts)[:120],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8890")
    ap.add_argument("--model", default="GLM-5.3-Flash-EXL3")
    ap.add_argument("--out", required=True)
    ap.add_argument("--rungs", default="8,16,32,64,128,256", help="k-token targets")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--max-tokens", type=int, default=8)
    ap.add_argument("--mem-floor-mb", type=int, default=1200)
    ap.add_argument("--timeout-s", type=float, default=1500)
    ap.add_argument("--thinking-kwargs", default='{"enable_thinking": false}')
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rungs = [int(r) for r in args.rungs.split(",")]
    thinking_kwargs = json.loads(args.thinking_kwargs)

    rec: dict = {"base": args.base, "model": args.model, "rungs": [], "aborted": False}
    for rung in rungs:
        for rep in range(1, args.repeats + 1):
            guard = MemoryGuard(args.mem_floor_mb)
            guard.start()
            salt = uuid.uuid4().hex
            prompt = build_prompt(rung * 1024, salt)
            row: dict = {"rung_k": rung, "repeat": rep, "salt": salt[:8]}
            try:
                if guard.low:
                    raise RuntimeError(f"MemAvailable below {args.mem_floor_mb}MB before request")
                t0 = time.perf_counter()
                result = stream_request(args.base, args.model, prompt, args.max_tokens,
                                        thinking_kwargs, args.timeout_s)
                ttft = result["ttft_s"]
                ptoks = result["prompt_tokens"]
                row.update(result)
                if ttft and ptoks:
                    row["prefill_tok_s"] = round(ptoks / ttft, 1)
                row["mem_min_mb"] = guard.min_seen
                row["elapsed_s"] = round(time.perf_counter() - t0, 2)
                ok = result["finish_reason"] is not None
                row["ok"] = ok
                print(json.dumps(row), flush=True)
            except Exception as exc:  # noqa: BLE001 - record and decide below
                guard.stop()
                row["ok"] = False
                row["error"] = f"{type(exc).__name__}: {exc}"
                row["mem_min_mb"] = guard.min_seen
                rec["rungs"].append(row)
                print(json.dumps(row), flush=True)
                if isinstance(exc, RuntimeError) and "MemAvailable" in str(exc):
                    rec["aborted"] = True
                    rec["abort_reason"] = str(exc)
                    break
                # A failed request (server died) also stops the ladder.
                rec["aborted"] = True
                rec["abort_reason"] = f"request failed: {row['error']}"
                break
            guard.stop()
            rec["rungs"].append(row)
            time.sleep(2)
        if rec["aborted"]:
            break

    good = [r for r in rec["rungs"] if r.get("ok") and r.get("prefill_tok_s")]
    rec["summary"] = {
        r["rung_k"]: {
            "prefill_tok_s_best": max(x["prefill_tok_s"] for x in good if x["rung_k"] == r["rung_k"]),
            "ttft_s_best": min(x["ttft_s"] for x in good if x["rung_k"] == r["rung_k"]),
        }
        for r in good
        for _ in [0]
        if any(x["rung_k"] == r["rung_k"] for x in good)
    }
    rec["mem_min_overall_mb"] = min(
        [x["mem_min_mb"] for x in rec["rungs"] if x.get("mem_min_mb") is not None] or [-1]
    )
    out.write_text(json.dumps(rec, indent=2))
    print("wrote", out, flush=True)
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
