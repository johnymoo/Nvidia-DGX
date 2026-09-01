#!/usr/bin/env python3
"""D0 probe battery (run from the lead workstation against the service API).

Per root-cause doc §7.3, all temperature 0, streamed to capture TTFT:
  A   850 random words (≈3K tokens), max_tokens 1   — pure short prefill
  A'  byte-identical A again, max_tokens 1           — the controlled repeat
  B   5650 random words (≈20K tokens, ≥3 chunked-prefill passes), max_tokens 200
      — exercises the MTP decode boundary
Word→token ratio calibrated from the A1 campaign (17,000 words = 60,163 tokens
≈ 3.54 tok/word).

Appends one JSON line per probe to --meta; the same file feeds analyze_d0.py
(probe time windows + ttft are the analysis join keys). Also prints the
A/A' answer-equality canary (any divergence = corruption = instant kill).
"""
import argparse
import hashlib
import json
import random
import string
import time
import urllib.request

API = "http://192.168.88.181:8890/v1/chat/completions"
MODEL = "deepseek-v4-flash-0731"

PROBES = (
    {"probe": "A", "n_words": 850, "seed": 41001, "max_tokens": 1},
    {"probe": "A2", "n_words": 850, "seed": 41001, "max_tokens": 1},  # byte-identical to A
    {"probe": "B", "n_words": 5650, "seed": 41002, "max_tokens": 200},
)


def rand_words(n_words: int, seed: int) -> str:
    rng = random.Random(seed)
    words = []
    for _ in range(n_words):
        w = "".join(rng.choices(string.ascii_lowercase, k=rng.randint(3, 9)))
        words.append(w)
    return " ".join(words)


def stream_request(prompt: str, max_tokens: int, timeout: int = 1800):
    """SSE stream; returns (ttft, total_s, usage, answer_text)."""
    body = json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
            "chat_template_kwargs": {"thinking": False},
            "stream": True,
            "stream_options": {"include_usage": True},
        }
    ).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    ttft = None
    answer = []
    usage = {}
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: "):
                continue
            data = line[len("data: "):]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            if chunk.get("usage"):
                usage = chunk["usage"]
            choices = chunk.get("choices") or []
            if choices:
                delta = choices[0].get("delta") or {}
                piece = delta.get("content") or delta.get("reasoning_content") or ""
                if piece:
                    if ttft is None:
                        ttft = time.time() - t0
                    answer.append(piece)
    return ttft, time.time() - t0, usage, "".join(answer)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True, help="JSONL out (append); feeds analyze_d0.py")
    a = ap.parse_args()

    records = {}
    for spec in PROBES:
        prompt = rand_words(spec["n_words"], spec["seed"])
        rec = dict(spec)
        rec["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
        ttft, total, usage, answer = stream_request(prompt, spec["max_tokens"])
        rec.update(
            ttft_s=round(ttft, 3) if ttft is not None else None,
            latency_s=round(total, 3),
            prompt_tokens=usage.get("prompt_tokens"),
            cached_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            answer_head=answer[:80],
        )
        # Event correlation needs the request's wall-clock window; the analysis
        # join is (start_epoch, end_epoch) against event recv_ts. Sending time
        # is reconstructed as now - latency (second-level precision suffices).
        now = time.time()
        rec["end_epoch"] = round(now, 3)
        rec["start_epoch"] = round(now - total, 3)
        records[spec["probe"]] = rec
        with open(a.meta, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        print(json.dumps({k: rec[k] for k in ("probe", "prompt_tokens", "cached_tokens", "completion_tokens", "ttft_s", "latency_s")}))

    a_ans = records["A"]["answer_head"]
    a2_ans = records["A2"]["answer_head"]
    print(json.dumps({"canary_A_equals_A2": a_ans == a2_ans, "A": a_ans, "A2": a2_ans}))


if __name__ == "__main__":
    main()
